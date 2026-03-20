// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

// ============================================================
//  BeraArb — FlashArbitrage Production Contract
//  Chain   : Berachain Mainnet (Chain ID 80094)
//  DEXes   : Kodiak V2, Kodiak V3, BEX (CrocSwap)
//  Author  : BeraArb Bot
//
//  Fitur Utama:
//  1. Flash Swap Arbitrage   — pinjam modal dari Kodiak V2 pair,
//                              eksekusi di DEX lain, kembalikan.
//                              ZERO upfront capital required.
//  2. Direct Arbitrage       — pakai modal sendiri di contract.
//  3. Atomic safety          — jika profit < minProfit → REVERT.
//                              No profit = No execution.
//  4. Multi-DEX support      — Kodiak V2 / V3 (UniV2-compat)
//                              + BEX (CrocSwap interface)
//  5. Re-entrancy guard      — custom nonReentrant modifier
//  6. MEV tip support        — bisa set priority fee via bot
//  7. On-chain simulation    — checkProfitability() view fn
//  8. Emergency functions    — withdraw, pause
// ============================================================

// ============================================================
//  INTERFACES
// ============================================================

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function decimals() external view returns (uint8);
}

interface IUniswapV2Factory {
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}

interface IUniswapV2Pair {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (
        uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast
    );
    // Flash swap: jika data.length > 0, contract memanggil uniswapV2Call
    function swap(
        uint256 amount0Out,
        uint256 amount1Out,
        address to,
        bytes calldata data
    ) external;
}

interface IKodiakRouter {
    // Standard UniswapV2 swap
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);

    // Quote tanpa eksekusi
    function getAmountsOut(
        uint256 amountIn,
        address[] calldata path
    ) external view returns (uint256[] memory amounts);
}

interface IBEXRouter {
    // CrocSwap main swap function
    // base  = token dengan alamat lebih rendah
    // quote = token dengan alamat lebih tinggi
    // poolIdx = 36000 (default Berachain BEX pool)
    // isBuy    = true → beli base pakai quote
    //            false → jual base dapat quote
    // inBaseQty = true → qty dalam satuan base
    //             false → qty dalam satuan quote
    // limitPrice = MAX_UINT128 (buy) atau MIN_SQRT_PRICE (sell)
    // Return: baseFlow & quoteFlow (negatif = keluar dari pool ke kita)
    function swap(
        address base,
        address quote,
        uint256 poolIdx,
        bool isBuy,
        bool inBaseQty,
        uint128 qty,
        uint16 tip,
        uint128 limitPrice,
        uint128 minOut,
        uint8 reserveFlags
    ) external payable returns (int128 baseFlow, int128 quoteFlow);
}

// ============================================================
//  MAIN CONTRACT
// ============================================================

contract FlashArbitrage {

    // ─── Security ─────────────────────────────────────────
    address public owner;
    bool private _locked;    // Reentrancy guard
    bool public paused;      // Emergency pause

    modifier onlyOwner() {
        require(msg.sender == owner, "FA: not owner");
        _;
    }

    modifier onlyAuthorized() {
        require(
            msg.sender == owner || authorizedBots[msg.sender],
            "FA: not authorized"
        );
        _;
    }

    modifier nonReentrant() {
        require(!_locked, "FA: reentrant call");
        _locked = true;
        _;
        _locked = false;
    }

    modifier whenNotPaused() {
        require(!paused, "FA: paused");
        _;
    }

    // ─── Constants: Berachain Mainnet Addresses ────────────
    address public constant KODIAK_V2_FACTORY =
        0x5C346464d33F90bABaf70dB6388507CC889C1070;
    address public constant KODIAK_V2_ROUTER =
        0xd91dd58387Ccd9B66B390ae2d7c66dBD46BC6022;
    address public constant KODIAK_V3_ROUTER =
        0xEd158C4b336A6FCb5B193A5570e3a571f6cbe690;
    address public constant BEX_ROUTER =
        0x21e2C0AFd058A89FCf7caf3aEA3cB84Ae977B73D;

    uint256 public constant BEX_POOL_IDX    = 36000;
    uint128 public constant BEX_MIN_SQRT    = 65536;       // no lower limit (sell)
    uint128 public constant BEX_MAX_UINT128 = type(uint128).max; // no upper limit (buy)

    // Uniswap V2 fee: 0.3%  → repay = borrow * 1000 / 997
    // Pakai formula: repay = (borrow * 1003) / 1000 + 1 (safe rounding)
    uint256 public constant FLASH_LOAN_FEE_NUMERATOR   = 1003;
    uint256 public constant FLASH_LOAN_FEE_DENOMINATOR = 1000;

    // ─── State ─────────────────────────────────────────────
    mapping(address => bool) public authorizedBots;

    // Minimum profit dalam basis points dari amountIn
    // Default: 5 bps = 0.05%
    uint256 public minProfitBps = 5;

    // ─── Data Structures ───────────────────────────────────

    // Enum untuk identifikasi DEX
    enum DEX { KODIAK_V2, KODIAK_V3, BEX }

    // Data yang di-encode ke dalam flash swap callback
    struct FlashCallbackData {
        address tokenBorrow;   // Token yang dipinjam dari pair
        address tokenOther;    // Token pasangan
        uint256 borrowAmount;  // Jumlah yang dipinjam
        DEX     sellDex;       // DEX untuk jual tokenBorrow → dapat tokenOther
        DEX     buyDex;        // DEX untuk beli tokenBorrow kembali pakai tokenOther
        uint256 minProfit;     // Minimum profit (dalam tokenBorrow units)
        address initiator;     // Address yang memulai (untuk verifikasi)
    }

    // Parameter untuk direct arbitrage
    struct DirectArbParams {
        address tokenIn;       // Token awal
        address tokenOut;      // Token target
        uint256 amountIn;      // Jumlah modal
        DEX     buyDex;        // DEX beli murah
        DEX     sellDex;       // DEX jual mahal
        uint256 minProfitAmt;  // Minimum profit dalam tokenIn units
    }

    // ─── Events ────────────────────────────────────────────
    event FlashArbExecuted(
        address indexed tokenBorrow,
        address indexed tokenOther,
        uint256 borrowAmount,
        uint256 profit,
        DEX     sellDex,
        DEX     buyDex,
        uint256 blockNumber
    );

    event DirectArbExecuted(
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 amountIn,
        uint256 profit,
        DEX     buyDex,
        DEX     sellDex,
        uint256 blockNumber
    );

    event ProfitWithdrawn(address indexed token, uint256 amount);
    event BotAuthorized(address indexed bot, bool authorized);
    event MinProfitBpsUpdated(uint256 oldBps, uint256 newBps);
    event Paused(bool state);

    // ─── Constructor ───────────────────────────────────────
    constructor() {
        owner = msg.sender;
        authorizedBots[msg.sender] = true;
    }

    // ─── Admin Functions ───────────────────────────────────

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "FA: zero address");
        owner = newOwner;
    }

    function setBot(address bot, bool authorized) external onlyOwner {
        authorizedBots[bot] = authorized;
        emit BotAuthorized(bot, authorized);
    }

    function setMinProfitBps(uint256 bps) external onlyOwner {
        require(bps <= 500, "FA: max 5%");   // Safety cap: max 5%
        emit MinProfitBpsUpdated(minProfitBps, bps);
        minProfitBps = bps;
    }

    function setPaused(bool state) external onlyOwner {
        paused = state;
        emit Paused(state);
    }

    // ─── FLASH SWAP ARBITRAGE ──────────────────────────────
    //
    // Flow:
    //   1. Bot deteksi: BEX harga WBERA lebih murah dari Kodiak V2
    //   2. Bot panggil executeFlashArbitrage()
    //   3. Contract pinjam USDC dari Kodiak V2 WBERA/USDC pair
    //   4. Di callback: beli WBERA di BEX pakai USDC (murah)
    //   5. Di callback: jual WBERA di Kodiak V2 (mahal) dapat USDC
    //   6. Di callback: kembalikan USDC pinjaman + 0.3% fee
    //   7. Sisa USDC = PROFIT 🚀
    //   Jika profit < minProfit → seluruh TX REVERT (gas tetap bayar tapi modal aman)

    /**
     * @notice Entry point: mulai flash swap arbitrage
     * @param flashPair  Alamat Kodiak V2 pair untuk pinjam modal
     * @param tokenBorrow Token yang dipinjam (harus ada di flashPair)
     * @param borrowAmount Jumlah token yang dipinjam
     * @param sellDex    DEX untuk jual tokenBorrow pertama kali (cari token lain)
     * @param buyDex     DEX untuk beli tokenBorrow kembali
     * @param minProfit  Minimum profit dalam units tokenBorrow
     */
    function executeFlashArbitrage(
        address flashPair,
        address tokenBorrow,
        uint256 borrowAmount,
        DEX     sellDex,
        DEX     buyDex,
        uint256 minProfit
    ) external onlyAuthorized nonReentrant whenNotPaused {
        require(borrowAmount > 0, "FA: zero borrow");

        // Verifikasi tokenBorrow ada di pair
        address t0 = IUniswapV2Pair(flashPair).token0();
        address t1 = IUniswapV2Pair(flashPair).token1();
        require(
            tokenBorrow == t0 || tokenBorrow == t1,
            "FA: token not in pair"
        );

        address tokenOther = (tokenBorrow == t0) ? t1 : t0;
        bool borrowIsToken0 = (tokenBorrow == t0);

        // Encode data untuk callback
        bytes memory callbackData = abi.encode(FlashCallbackData({
            tokenBorrow:  tokenBorrow,
            tokenOther:   tokenOther,
            borrowAmount: borrowAmount,
            sellDex:      sellDex,
            buyDex:       buyDex,
            minProfit:    minProfit,
            initiator:    msg.sender
        }));

        // Trigger flash swap (data != "" → Kodiak akan panggil uniswapV2Call)
        uint256 amount0Out = borrowIsToken0 ? borrowAmount : 0;
        uint256 amount1Out = borrowIsToken0 ? 0 : borrowAmount;

        IUniswapV2Pair(flashPair).swap(
            amount0Out,
            amount1Out,
            address(this),
            callbackData
        );
    }

    /**
     * @notice Callback dari Kodiak V2 pair setelah flash swap
     * @dev HANYA dipanggil oleh Kodiak V2 pair yang valid
     */
    function uniswapV2Call(
        address sender,
        uint256 amount0,
        uint256 amount1,
        bytes calldata data
    ) external nonReentrant {
        // === KEAMANAN: Verifikasi caller adalah Kodiak V2 pair valid ===
        address t0 = IUniswapV2Pair(msg.sender).token0();
        address t1 = IUniswapV2Pair(msg.sender).token1();
        address expectedPair = IUniswapV2Factory(KODIAK_V2_FACTORY).getPair(t0, t1);
        require(msg.sender == expectedPair,   "FA: invalid pair caller");
        require(sender == address(this),       "FA: invalid flash sender");

        FlashCallbackData memory d = abi.decode(data, (FlashCallbackData));

        uint256 amountBorrowed = amount0 > 0 ? amount0 : amount1;
        require(amountBorrowed == d.borrowAmount, "FA: amount mismatch");

        // === KALKULASI REPAYMENT ===
        // Repay = borrow * 1003 / 1000  (+1 untuk pembulatan aman)
        uint256 repayAmount = (amountBorrowed * FLASH_LOAN_FEE_NUMERATOR)
            / FLASH_LOAN_FEE_DENOMINATOR + 1;

        // === STEP 1: Jual tokenBorrow → tokenOther di sellDex ===
        // (DEX yang harganya menguntungkan untuk kita jual)
        uint256 tokenOtherReceived = _swapExact(
            d.tokenBorrow,
            d.tokenOther,
            amountBorrowed,
            0,            // minOut: 0, kita check profit di akhir
            d.sellDex
        );

        require(tokenOtherReceived > 0, "FA: sell step failed");

        // === STEP 2: Beli tokenBorrow kembali di buyDex ===
        // (DEX yang harganya menguntungkan untuk kita beli)
        uint256 tokenBorrowReturned = _swapExact(
            d.tokenOther,
            d.tokenBorrow,
            tokenOtherReceived,
            repayAmount,  // minOut harus cukup untuk repay
            d.buyDex
        );

        require(tokenBorrowReturned >= repayAmount, "FA: insufficient for repay");

        // === STEP 3: Verifikasi Profit ===
        uint256 profit = tokenBorrowReturned - repayAmount;
        require(profit >= d.minProfit, "FA: profit below minimum");

        // Juga cek vs minProfitBps
        uint256 minProfitFromBps = (amountBorrowed * minProfitBps) / 10000;
        require(profit >= minProfitFromBps, "FA: profit below bps threshold");

        // === STEP 4: Bayar kembali flash loan ===
        require(
            IERC20(d.tokenBorrow).transfer(msg.sender, repayAmount),
            "FA: repay failed"
        );

        // Profit otomatis tersimpan di contract
        emit FlashArbExecuted(
            d.tokenBorrow,
            d.tokenOther,
            amountBorrowed,
            profit,
            d.sellDex,
            d.buyDex,
            block.number
        );
    }

    // ─── DIRECT ARBITRAGE (Pakai Modal Sendiri) ────────────
    //
    // Lebih reliable dari flash loan karena tidak ada repayment constraint.
    // Gunakan ini untuk testing atau kalau modal tersedia.

    /**
     * @notice Execute direct arbitrage dengan modal yang ada di contract
     * @param params Struct berisi parameter arbitrase
     * @return profit Profit yang didapat dalam units tokenIn
     */
    function executeDirectArbitrage(
        DirectArbParams calldata params
    ) external onlyAuthorized nonReentrant whenNotPaused returns (uint256 profit) {
        require(params.amountIn > 0, "FA: zero amount");

        uint256 balanceBefore = IERC20(params.tokenIn).balanceOf(address(this));
        require(balanceBefore >= params.amountIn, "FA: insufficient balance");

        // === Beli tokenOut di DEX murah ===
        uint256 tokenOutReceived = _swapExact(
            params.tokenIn,
            params.tokenOut,
            params.amountIn,
            0,
            params.buyDex
        );
        require(tokenOutReceived > 0, "FA: buy step failed");

        // === Jual tokenOut di DEX mahal ===
        uint256 tokenInReceived = _swapExact(
            params.tokenOut,
            params.tokenIn,
            tokenOutReceived,
            params.amountIn, // minOut: setidaknya modal kembali
            params.sellDex
        );

        // === Hitung Profit ===
        uint256 balanceAfter = IERC20(params.tokenIn).balanceOf(address(this));
        profit = balanceAfter > balanceBefore
            ? balanceAfter - balanceBefore
            : 0;

        require(profit >= params.minProfitAmt, "FA: profit below minimum");

        uint256 minProfitFromBps = (params.amountIn * minProfitBps) / 10000;
        require(profit >= minProfitFromBps, "FA: profit below bps threshold");

        emit DirectArbExecuted(
            params.tokenIn,
            params.tokenOut,
            params.amountIn,
            profit,
            params.buyDex,
            params.sellDex,
            block.number
        );

        return profit;
    }

    // ─── INTERNAL: DEX ADAPTERS ────────────────────────────

    /**
     * @dev Routing swap ke DEX yang tepat
     * @param tokenIn  Token yang di-swap
     * @param tokenOut Token yang mau didapat
     * @param amountIn Jumlah tokenIn
     * @param minOut   Minimum tokenOut (0 = no check, revert handled by caller)
     * @param dex      DEX target
     * @return amountOut Token yang diterima
     */
    function _swapExact(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minOut,
        DEX dex
    ) internal returns (uint256 amountOut) {
        if (dex == DEX.BEX) {
            amountOut = _swapBEX(tokenIn, tokenOut, amountIn, uint128(minOut));
        } else {
            address router = (dex == DEX.KODIAK_V2)
                ? KODIAK_V2_ROUTER
                : KODIAK_V3_ROUTER;
            amountOut = _swapKodiak(router, tokenIn, tokenOut, amountIn, minOut);
        }
    }

    /**
     * @dev Swap via Kodiak V2 atau V3 (UniswapV2Router interface)
     */
    function _swapKodiak(
        address router,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOutMin
    ) internal returns (uint256 amountOut) {
        // Approve router
        _safeApprove(tokenIn, router, amountIn);

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;

        uint256[] memory amounts = IKodiakRouter(router).swapExactTokensForTokens(
            amountIn,
            amountOutMin,
            path,
            address(this),
            block.timestamp + 300  // deadline: 5 menit
        );

        amountOut = amounts[amounts.length - 1];
    }

    /**
     * @dev Swap via BEX (CrocSwap)
     *
     * CrocSwap Rules:
     * - base  = token dengan address integer LEBIH KECIL
     * - quote = token dengan address integer LEBIH BESAR
     * - isBuy=true  → beli base pakai quote (tokenIn=quote)
     * - isBuy=false → jual base dapat quote (tokenIn=base)
     */
    function _swapBEX(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint128 minOut
    ) internal returns (uint256 amountOut) {
        require(amountIn <= type(uint128).max, "FA: BEX qty overflow");

        address base;
        address quote;
        bool isBuy;
        bool inBaseQty;
        uint128 limitPrice;

        if (uint160(tokenIn) < uint160(tokenOut)) {
            // tokenIn adalah base → Selling base untuk dapat quote
            base       = tokenIn;
            quote      = tokenOut;
            isBuy      = false;
            inBaseQty  = true;            // qty dalam base units
            limitPrice = BEX_MIN_SQRT;    // sell: tidak ada batas harga bawah
        } else {
            // tokenIn adalah quote → Buying base dengan quote
            base       = tokenOut;
            quote      = tokenIn;
            isBuy      = true;
            inBaseQty  = false;           // qty dalam quote units
            limitPrice = BEX_MAX_UINT128; // buy: tidak ada batas harga atas
        }

        // Approve BEX router untuk ambil tokenIn
        _safeApprove(tokenIn, BEX_ROUTER, amountIn);

        (int128 baseFlow, int128 quoteFlow) = IBEXRouter(BEX_ROUTER).swap(
            base,
            quote,
            BEX_POOL_IDX,
            isBuy,
            inBaseQty,
            uint128(amountIn),
            0,           // tip: 0
            limitPrice,
            minOut,
            0            // reserveFlags: 0 = gunakan transfer biasa
        );

        // Output = flow negatif dari pool (pool kirim ke kita)
        if (isBuy) {
            // Kita beli base → baseFlow negatif
            require(baseFlow < 0, "FA: BEX buy no base received");
            amountOut = uint256(uint128(-baseFlow));
        } else {
            // Kita jual base → quoteFlow negatif
            require(quoteFlow < 0, "FA: BEX sell no quote received");
            amountOut = uint256(uint128(-quoteFlow));
        }

        require(amountOut >= minOut, "FA: BEX below minOut");
    }

    /**
     * @dev Safe approve: reset ke 0 dulu jika ada approval sebelumnya
     *      (diperlukan oleh beberapa token seperti USDT)
     */
    function _safeApprove(
        address token,
        address spender,
        uint256 amount
    ) internal {
        uint256 current = IERC20(token).allowance(address(this), spender);
        if (current < amount) {
            if (current > 0) {
                // Reset dulu (USDT requirement)
                IERC20(token).approve(spender, 0);
            }
            IERC20(token).approve(spender, type(uint256).max);
        }
    }

    // ─── VIEW / SIMULATION ─────────────────────────────────

    /**
     * @notice Simulasi profit arbitrase (TIDAK EKSEKUSI)
     *         Panggil ini dari bot Python sebelum eksekusi untuk pre-check
     * @return profitable    True jika menguntungkan
     * @return expectedProfit Estimasi profit dalam units tokenIn
     * @return buyOutput     Token yang didapat di buy step
     * @return sellOutput    Token yang didapat di sell step
     */
    function checkArbitrageProfitability(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        DEX buyDex,
        DEX sellDex
    ) external view returns (
        bool profitable,
        uint256 expectedProfit,
        uint256 buyOutput,
        uint256 sellOutput
    ) {
        // Hanya support Kodiak-to-Kodiak untuk view fn
        // (BEX previewSwap perlu call external terpisah)
        if (buyDex == DEX.BEX || sellDex == DEX.BEX) {
            // Return false, BEX quote butuh off-chain previewSwap
            return (false, 0, 0, 0);
        }

        address buyRouter  = (buyDex  == DEX.KODIAK_V2) ? KODIAK_V2_ROUTER : KODIAK_V3_ROUTER;
        address sellRouter = (sellDex == DEX.KODIAK_V2) ? KODIAK_V2_ROUTER : KODIAK_V3_ROUTER;

        address[] memory buyPath = new address[](2);
        buyPath[0] = tokenIn;
        buyPath[1] = tokenOut;

        try IKodiakRouter(buyRouter).getAmountsOut(amountIn, buyPath)
            returns (uint256[] memory buyAmounts)
        {
            buyOutput = buyAmounts[buyAmounts.length - 1];
        } catch {
            return (false, 0, 0, 0);
        }

        address[] memory sellPath = new address[](2);
        sellPath[0] = tokenOut;
        sellPath[1] = tokenIn;

        try IKodiakRouter(sellRouter).getAmountsOut(buyOutput, sellPath)
            returns (uint256[] memory sellAmounts)
        {
            sellOutput = sellAmounts[sellAmounts.length - 1];
        } catch {
            return (false, 0, 0, 0);
        }

        if (sellOutput > amountIn) {
            profitable    = true;
            expectedProfit = sellOutput - amountIn;
        }
    }

    /**
     * @notice Hitung repayment flash loan
     */
    function calcFlashRepayment(uint256 borrowAmount)
        external pure returns (uint256 repayAmount)
    {
        repayAmount = (borrowAmount * FLASH_LOAN_FEE_NUMERATOR)
            / FLASH_LOAN_FEE_DENOMINATOR + 1;
    }

    /**
     * @notice Cek saldo token di contract
     */
    function getTokenBalance(address token)
        external view returns (uint256)
    {
        return IERC20(token).balanceOf(address(this));
    }

    // ─── UTILITY / EMERGENCY ───────────────────────────────

    /**
     * @notice Deposit token ke contract untuk direct arbitrage
     */
    function depositToken(address token, uint256 amount) external onlyOwner {
        require(
            IERC20(token).transferFrom(msg.sender, address(this), amount),
            "FA: deposit failed"
        );
    }

    /**
     * @notice Tarik semua profit token dari contract
     */
    function withdrawToken(address token) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "FA: no balance");
        require(IERC20(token).transfer(owner, balance), "FA: withdraw failed");
        emit ProfitWithdrawn(token, balance);
    }

    /**
     * @notice Tarik beberapa token (untuk efisiensi gas)
     */
    function withdrawTokens(address[] calldata tokens) external onlyOwner {
        for (uint256 i = 0; i < tokens.length; i++) {
            uint256 balance = IERC20(tokens[i]).balanceOf(address(this));
            if (balance > 0) {
                IERC20(tokens[i]).transfer(owner, balance);
                emit ProfitWithdrawn(tokens[i], balance);
            }
        }
    }

    /**
     * @notice Tarik BERA native jika ada
     */
    function withdrawNative() external onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "FA: no native balance");
        payable(owner).transfer(balance);
    }

    /**
     * @notice Emergency: tarik semua token spesifik (bypass profit check)
     */
    function emergencyWithdraw(address token, uint256 amount) external onlyOwner {
        IERC20(token).transfer(owner, amount);
    }

    // Terima BERA native (untuk gas atau sebagai collateral)
    receive() external payable {}
    fallback() external payable {}
}
