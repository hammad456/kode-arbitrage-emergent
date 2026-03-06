import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { 
    Wallet, 
    TrendingUp, 
    Activity, 
    Zap, 
    RefreshCw, 
    Settings, 
    BarChart3,
    Fuel,
    AlertCircle,
    ChevronRight,
    CheckCircle2,
    XCircle,
    Loader2
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { useWallet } from '@/context/WalletContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { 
    Dialog, 
    DialogContent, 
    DialogHeader, 
    DialogTitle,
    DialogFooter 
} from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const WS_URL = API_URL?.replace('https://', 'wss://').replace('http://', 'ws://');

export default function Dashboard() {
    const { 
        account, 
        isConnected, 
        connect, 
        isConnecting, 
        formatAddress, 
        balances: walletBalances,
        executeTrade,
        refreshBalances 
    } = useWallet();
    
    const [opportunities, setOpportunities] = useState([]);
    const [gasPrice, setGasPrice] = useState(null);
    const [balances, setBalances] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedOpp, setSelectedOpp] = useState(null);
    const [tradeModalOpen, setTradeModalOpen] = useState(false);
    const [slippage, setSlippage] = useState([0.5]);
    const [tradeAmount, setTradeAmount] = useState('100');
    const [executing, setExecuting] = useState(false);
    const [tradeResult, setTradeResult] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [lastUpdate, setLastUpdate] = useState(new Date());
    const [wsConnected, setWsConnected] = useState(false);
    
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const pollingIntervalRef = useRef(null);

    // Fetch data via REST API (fallback when WebSocket unavailable)
    const fetchDataREST = useCallback(async () => {
        try {
            const [oppRes, gasRes] = await Promise.all([
                axios.get(`${API_URL}/api/opportunities`),
                axios.get(`${API_URL}/api/gas-price`)
            ]);
            
            setOpportunities(oppRes.data);
            setGasPrice(gasRes.data);
            setLastUpdate(new Date());
            setLoading(false);
        } catch (error) {
            console.error('Failed to fetch data:', error);
            setLoading(false);
        }
    }, []);

    // WebSocket connection with REST API fallback
    const connectWebSocket = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        try {
            const ws = new WebSocket(`${WS_URL}/ws/prices`);
            
            ws.onopen = () => {
                console.log('WebSocket connected');
                setWsConnected(true);
                setLoading(false);
                // Clear polling if WebSocket connects
                if (pollingIntervalRef.current) {
                    clearInterval(pollingIntervalRef.current);
                    pollingIntervalRef.current = null;
                }
            };
            
            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'update') {
                        setOpportunities(data.opportunities || []);
                        setGasPrice(data.gas);
                        setLastUpdate(new Date());
                    }
                } catch (e) {
                    console.error('WebSocket message parse error:', e);
                }
            };
            
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                setWsConnected(false);
                // Start polling fallback
                if (!pollingIntervalRef.current) {
                    fetchDataREST();
                    pollingIntervalRef.current = setInterval(fetchDataREST, 5000);
                }
                // Reconnect after 5 seconds
                reconnectTimeoutRef.current = setTimeout(() => {
                    connectWebSocket();
                }, 5000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                setWsConnected(false);
                // Start polling fallback on error
                if (!pollingIntervalRef.current) {
                    fetchDataREST();
                    pollingIntervalRef.current = setInterval(fetchDataREST, 5000);
                }
            };
            
            wsRef.current = ws;
        } catch (error) {
            console.error('WebSocket connection error:', error);
            setLoading(false);
            // Fallback to polling
            if (!pollingIntervalRef.current) {
                fetchDataREST();
                pollingIntervalRef.current = setInterval(fetchDataREST, 5000);
            }
        }
    }, [fetchDataREST]);

    // Initialize WebSocket on mount
    useEffect(() => {
        connectWebSocket();
        
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current);
            }
        };
    }, [connectWebSocket]);

    // Fetch balances from API
    const fetchBalances = useCallback(async () => {
        if (!account) return;
        try {
            const res = await axios.get(`${API_URL}/api/wallet/${account}/balances`);
            setBalances(res.data.balances || []);
        } catch (error) {
            console.error('Failed to fetch balances:', error);
        }
    }, [account]);

    // Fetch analytics
    const fetchAnalytics = useCallback(async () => {
        if (!account) return;
        try {
            const res = await axios.get(`${API_URL}/api/analytics/${account}`);
            setAnalytics(res.data);
        } catch (error) {
            console.error('Failed to fetch analytics:', error);
        }
    }, [account]);

    useEffect(() => {
        if (account) {
            fetchBalances();
            fetchAnalytics();
        }
    }, [account, fetchBalances, fetchAnalytics]);

    // Execute trade handler
    const handleExecuteTrade = async () => {
        if (!selectedOpp || !account) {
            toast.error('Please connect wallet first');
            return;
        }
        
        setExecuting(true);
        setTradeResult(null);
        
        try {
            // Call backend to verify and build transaction
            const response = await axios.post(`${API_URL}/api/execute-trade`, {
                pair: selectedOpp.token_pair,
                buy_dex: selectedOpp.buy_dex,
                sell_dex: selectedOpp.sell_dex,
                amount: selectedOpp.amount_in,
                slippage: slippage[0],
                wallet_address: account
            });
            
            if (!response.data.success) {
                setTradeResult({
                    success: false,
                    error: response.data.error || 'Trade verification failed'
                });
                toast.error(response.data.error || 'Trade verification failed');
                return;
            }
            
            // Execute via MetaMask
            const result = await executeTrade(response.data.transaction);
            
            if (result.success) {
                setTradeResult({
                    success: true,
                    tx_hash: result.tx_hash,
                    estimated_profit: response.data.estimated_profit,
                    gas_used: result.gas_used
                });
                
                // Record trade
                await axios.post(`${API_URL}/api/trade/record`, {
                    wallet_address: account.toLowerCase(),
                    token_pair: selectedOpp.token_pair,
                    buy_dex: selectedOpp.buy_dex,
                    sell_dex: selectedOpp.sell_dex,
                    amount_in: selectedOpp.amount_in,
                    amount_out: selectedOpp.expected_out,
                    profit_usd: response.data.estimated_profit,
                    gas_used: parseInt(result.gas_used),
                    tx_hash: result.tx_hash,
                    status: 'success'
                });
                
                // Refresh data
                fetchBalances();
                fetchAnalytics();
                refreshBalances();
            } else {
                setTradeResult({
                    success: false,
                    error: result.error
                });
            }
        } catch (error) {
            console.error('Trade execution error:', error);
            setTradeResult({
                success: false,
                error: error.response?.data?.detail || error.message
            });
            toast.error('Trade failed: ' + (error.response?.data?.detail || error.message));
        } finally {
            setExecuting(false);
        }
    };

    const closeModal = () => {
        setTradeModalOpen(false);
        setSelectedOpp(null);
        setTradeResult(null);
    };

    return (
        <div className="min-h-screen bg-[#050505]">
            {/* Header */}
            <header className="header-gradient sticky top-0 z-50 border-b border-white/10">
                <div className="container mx-auto px-4 py-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#FF9F1C] to-[#FFD60A] flex items-center justify-center">
                                <Zap className="w-6 h-6 text-black" strokeWidth={2.5} />
                            </div>
                            <div>
                                <h1 className="text-xl font-bold tracking-tight">BeraArb</h1>
                                <p className="text-xs text-white/50">Berachain Arbitrage</p>
                            </div>
                        </div>

                        <nav className="hidden md:flex items-center gap-6">
                            <Link to="/" className="text-sm font-medium text-[#FF9F1C]">Dashboard</Link>
                            <Link to="/analytics" className="text-sm font-medium text-white/60 hover:text-white transition-colors">Analytics</Link>
                            <Link to="/settings" className="text-sm font-medium text-white/60 hover:text-white transition-colors">Settings</Link>
                        </nav>

                        <div className="flex items-center gap-3">
                            {/* Connection Status */}
                            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 text-xs">
                                <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[#39FF14]' : opportunities.length > 0 ? 'bg-[#FFD60A]' : 'bg-[#FF003C]'} ${wsConnected ? 'animate-pulse' : ''}`} />
                                <span className="text-white/50">
                                    {wsConnected ? 'Live' : opportunities.length > 0 ? 'Polling' : 'Connecting...'}
                                </span>
                            </div>
                            
                            {isConnected ? (
                                <Button 
                                    data-testid="wallet-connected-btn"
                                    className="wallet-btn connected flex items-center gap-2"
                                >
                                    <div className="live-indicator" />
                                    <span className="font-mono">{formatAddress(account)}</span>
                                </Button>
                            ) : (
                                <Button
                                    data-testid="connect-wallet-btn"
                                    onClick={connect}
                                    disabled={isConnecting}
                                    className="wallet-btn flex items-center gap-2"
                                >
                                    <Wallet className="w-4 h-4" />
                                    {isConnecting ? 'Connecting...' : 'Connect Wallet'}
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="container mx-auto px-4 py-6">
                {/* Stats Row */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                        <Card className="stat-card" data-testid="total-opportunities-card">
                            <CardContent className="p-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="label-text mb-1">Active Opportunities</p>
                                        <p className="value-large text-[#FF9F1C]">{opportunities.length}</p>
                                    </div>
                                    <div className="w-12 h-12 rounded-xl bg-[#FF9F1C]/20 flex items-center justify-center">
                                        <TrendingUp className="w-6 h-6 text-[#FF9F1C]" />
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </motion.div>

                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                        <Card className="stat-card secondary" data-testid="gas-price-card">
                            <CardContent className="p-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="label-text mb-1">Gas Price</p>
                                        <p className="value-large text-[#00F0FF]">
                                            {gasPrice ? (gasPrice.gwei < 0.01 ? '<0.01' : gasPrice.gwei.toFixed(2)) : '--'} 
                                            <span className="text-sm text-white/50 ml-1">gwei</span>
                                        </p>
                                    </div>
                                    <div className="w-12 h-12 rounded-xl bg-[#00F0FF]/20 flex items-center justify-center">
                                        <Fuel className="w-6 h-6 text-[#00F0FF]" />
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </motion.div>

                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
                        <Card className="stat-card success" data-testid="total-profit-card">
                            <CardContent className="p-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="label-text mb-1">Total Profit</p>
                                        <p className="value-large text-[#39FF14]">
                                            ${analytics?.total_profit_usd?.toFixed(2) || '0.00'}
                                        </p>
                                    </div>
                                    <div className="w-12 h-12 rounded-xl bg-[#39FF14]/20 flex items-center justify-center">
                                        <BarChart3 className="w-6 h-6 text-[#39FF14]" />
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </motion.div>

                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }}>
                        <Card className="glass-card" data-testid="success-rate-card">
                            <CardContent className="p-6">
                                <div className="flex items-center justify-between">
                                    <div>
                                        <p className="label-text mb-1">Success Rate</p>
                                        <p className="value-large text-white">
                                            {analytics?.success_rate?.toFixed(1) || '0'}%
                                        </p>
                                    </div>
                                    <div className="w-12 h-12 rounded-xl bg-white/10 flex items-center justify-center">
                                        <Activity className="w-6 h-6 text-white" />
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    </motion.div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Opportunities Table */}
                    <div className="lg:col-span-2">
                        <Card className="glass-card" data-testid="opportunities-table">
                            <CardHeader className="flex flex-row items-center justify-between pb-2">
                                <div className="flex items-center gap-3">
                                    <CardTitle className="text-xl">Arbitrage Opportunities</CardTitle>
                                    <div className="flex items-center gap-2 text-xs text-white/50">
                                        <div className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-[#39FF14] animate-pulse' : 'bg-[#FF003C]'}`} />
                                        <span>{wsConnected ? 'Real-time' : 'Reconnecting...'}</span>
                                    </div>
                                </div>
                                <div className="text-xs text-white/40">
                                    Updated: {lastUpdate.toLocaleTimeString()}
                                </div>
                            </CardHeader>
                            <CardContent>
                                <ScrollArea className="h-[500px] scrollbar-thin">
                                    {loading ? (
                                        <div className="space-y-4">
                                            {[1, 2, 3].map(i => (
                                                <div key={i} className="skeleton h-20 rounded-lg" />
                                            ))}
                                        </div>
                                    ) : opportunities.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center py-20 text-white/50">
                                            <AlertCircle className="w-12 h-12 mb-4" />
                                            <p>No arbitrage opportunities found</p>
                                            <p className="text-sm">Scanning for new opportunities...</p>
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            {opportunities.map((opp, idx) => (
                                                <motion.div
                                                    key={opp.id}
                                                    initial={{ opacity: 0, x: -20 }}
                                                    animate={{ opacity: 1, x: 0 }}
                                                    transition={{ delay: idx * 0.05 }}
                                                    className={`opportunity-card p-4 cursor-pointer ${opp.net_profit_usd > 1 ? 'high-profit' : ''}`}
                                                    onClick={() => {
                                                        setSelectedOpp(opp);
                                                        setTradeModalOpen(true);
                                                    }}
                                                    data-testid={`opportunity-${opp.id}`}
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <div className="flex items-center gap-4">
                                                            <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
                                                                <span className="text-sm font-bold">{opp.token_pair.split('/')[0].slice(0, 2)}</span>
                                                            </div>
                                                            <div>
                                                                <p className="font-semibold">{opp.token_pair}</p>
                                                                <p className="text-xs text-white/50">
                                                                    {opp.buy_dex} → {opp.sell_dex}
                                                                </p>
                                                            </div>
                                                        </div>
                                                        
                                                        <div className="flex items-center gap-6">
                                                            <div className="text-right">
                                                                <p className="text-xs text-white/50">Spread</p>
                                                                <p className="font-mono text-[#00F0FF]">
                                                                    {opp.spread_percent.toFixed(3)}%
                                                                </p>
                                                            </div>
                                                            
                                                            <div className="text-right">
                                                                <p className="text-xs text-white/50">Net Profit</p>
                                                                <p className={`font-mono font-bold ${opp.net_profit_usd > 0 ? 'text-[#39FF14]' : 'text-[#FF003C]'}`}>
                                                                    ${opp.net_profit_usd.toFixed(2)}
                                                                </p>
                                                            </div>
                                                            
                                                            <ChevronRight className="w-5 h-5 text-white/30" />
                                                        </div>
                                                    </div>
                                                    
                                                    <div className="mt-3 pt-3 border-t border-white/5 flex items-center justify-between text-xs">
                                                        <div className="flex items-center gap-4">
                                                            <span className="text-white/50">
                                                                Buy: <span className="text-white font-mono">{opp.buy_price.toFixed(6)}</span>
                                                            </span>
                                                            <span className="text-white/50">
                                                                Sell: <span className="text-white font-mono">{opp.sell_price.toFixed(6)}</span>
                                                            </span>
                                                        </div>
                                                        <span className="text-white/50">
                                                            Gas: <span className="text-[#FFD60A] font-mono">${opp.gas_cost_usd.toFixed(2)}</span>
                                                        </span>
                                                    </div>
                                                </motion.div>
                                            ))}
                                        </div>
                                    )}
                                </ScrollArea>
                            </CardContent>
                        </Card>
                    </div>

                    {/* Right Sidebar */}
                    <div className="space-y-6">
                        {/* Wallet Balances */}
                        <Card className="glass-card" data-testid="wallet-balances">
                            <CardHeader>
                                <CardTitle className="text-lg flex items-center gap-2">
                                    <Wallet className="w-5 h-5 text-[#FF9F1C]" />
                                    Portfolio
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                {!isConnected ? (
                                    <div className="text-center py-8">
                                        <p className="text-white/50 mb-4">Connect wallet to view balances</p>
                                        <Button onClick={connect} className="btn-primary">
                                            Connect Wallet
                                        </Button>
                                    </div>
                                ) : (
                                    <ScrollArea className="h-[200px]">
                                        <div className="space-y-3">
                                            {/* Show wallet context balances first */}
                                            <div className="flex items-center justify-between p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
                                                <div className="flex items-center gap-3">
                                                    <div className="w-8 h-8 rounded-full bg-[#FF9F1C]/20 flex items-center justify-center text-xs font-bold text-[#FF9F1C]">
                                                        BE
                                                    </div>
                                                    <span className="font-medium">BERA</span>
                                                </div>
                                                <div className="text-right">
                                                    <p className="font-mono text-sm">
                                                        {parseFloat(walletBalances.BERA || '0').toFixed(4)}
                                                    </p>
                                                </div>
                                            </div>
                                            <div className="flex items-center justify-between p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors">
                                                <div className="flex items-center gap-3">
                                                    <div className="w-8 h-8 rounded-full bg-[#FFD60A]/20 flex items-center justify-center text-xs font-bold text-[#FFD60A]">
                                                        HO
                                                    </div>
                                                    <span className="font-medium">HONEY</span>
                                                </div>
                                                <div className="text-right">
                                                    <p className="font-mono text-sm">
                                                        {parseFloat(walletBalances.HONEY || '0').toFixed(4)}
                                                    </p>
                                                </div>
                                            </div>
                                            {balances.filter(b => b.symbol !== 'BERA' && b.symbol !== 'HONEY').map((balance) => (
                                                <div 
                                                    key={balance.symbol} 
                                                    className="flex items-center justify-between p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                                                >
                                                    <div className="flex items-center gap-3">
                                                        <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center text-xs font-bold">
                                                            {balance.symbol.slice(0, 2)}
                                                        </div>
                                                        <span className="font-medium">{balance.symbol}</span>
                                                    </div>
                                                    <div className="text-right">
                                                        <p className="font-mono text-sm">
                                                            {parseFloat(balance.balance_formatted).toFixed(4)}
                                                        </p>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </ScrollArea>
                                )}
                            </CardContent>
                        </Card>

                        {/* Gas Recommendations */}
                        <Card className="glass-card" data-testid="gas-recommendations">
                            <CardHeader>
                                <CardTitle className="text-lg flex items-center gap-2">
                                    <Fuel className="w-5 h-5 text-[#00F0FF]" />
                                    Gas Settings
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                {gasPrice?.recommended && (
                                    <div className="space-y-3">
                                        {Object.entries(gasPrice.recommended).map(([speed, price]) => (
                                            <div 
                                                key={speed} 
                                                className="flex items-center justify-between p-3 rounded-lg bg-white/5"
                                            >
                                                <span className="capitalize text-white/70">{speed}</span>
                                                <span className="font-mono text-[#00F0FF]">
                                                    {price < 0.01 ? '<0.01' : price.toFixed(2)} gwei
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        {/* Quick Actions */}
                        <Card className="glass-card" data-testid="quick-actions">
                            <CardHeader>
                                <CardTitle className="text-lg">Quick Actions</CardTitle>
                            </CardHeader>
                            <CardContent className="space-y-3">
                                <Link to="/settings" className="block">
                                    <Button variant="outline" className="w-full justify-start gap-2 border-white/10 hover:bg-white/5">
                                        <Settings className="w-4 h-4" />
                                        Configure Bot Settings
                                    </Button>
                                </Link>
                                <Link to="/analytics" className="block">
                                    <Button variant="outline" className="w-full justify-start gap-2 border-white/10 hover:bg-white/5">
                                        <BarChart3 className="w-4 h-4" />
                                        View Analytics
                                    </Button>
                                </Link>
                            </CardContent>
                        </Card>
                    </div>
                </div>
            </main>

            {/* Trade Execution Modal */}
            <Dialog open={tradeModalOpen} onOpenChange={closeModal}>
                <DialogContent className="trade-modal sm:max-w-[500px]" data-testid="trade-modal">
                    <DialogHeader>
                        <DialogTitle className="text-xl">
                            {tradeResult ? (tradeResult.success ? 'Trade Successful!' : 'Trade Failed') : 'Execute Arbitrage Trade'}
                        </DialogTitle>
                    </DialogHeader>
                    
                    {tradeResult ? (
                        // Trade result view
                        <div className="space-y-6 py-4">
                            <div className="flex flex-col items-center justify-center py-6">
                                {tradeResult.success ? (
                                    <>
                                        <CheckCircle2 className="w-16 h-16 text-[#39FF14] mb-4" />
                                        <p className="text-lg font-semibold text-[#39FF14]">Trade Executed Successfully!</p>
                                        <p className="text-sm text-white/50 mt-2">
                                            Estimated profit: <span className="text-[#39FF14] font-mono">${tradeResult.estimated_profit?.toFixed(2)}</span>
                                        </p>
                                        {tradeResult.tx_hash && (
                                            <a 
                                                href={`https://berascan.com/tx/${tradeResult.tx_hash}`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="mt-4 text-sm text-[#00F0FF] hover:underline"
                                            >
                                                View on Berascan →
                                            </a>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        <XCircle className="w-16 h-16 text-[#FF003C] mb-4" />
                                        <p className="text-lg font-semibold text-[#FF003C]">Trade Failed</p>
                                        <p className="text-sm text-white/50 mt-2 text-center">
                                            {tradeResult.error}
                                        </p>
                                    </>
                                )}
                            </div>
                            <DialogFooter>
                                <Button onClick={closeModal} className="w-full btn-secondary">
                                    Close
                                </Button>
                            </DialogFooter>
                        </div>
                    ) : selectedOpp && (
                        // Trade confirmation view
                        <div className="space-y-6 py-4">
                            {/* Trade Details */}
                            <div className="glass-card p-4 rounded-lg">
                                <div className="flex items-center justify-between mb-4">
                                    <span className="text-lg font-semibold">{selectedOpp.token_pair}</span>
                                    <Badge variant="outline" className="bg-[#39FF14]/20 text-[#39FF14] border-[#39FF14]/30">
                                        {selectedOpp.spread_percent.toFixed(3)}% spread
                                    </Badge>
                                </div>
                                
                                <div className="space-y-3">
                                    <div className="flex justify-between text-sm">
                                        <span className="text-white/50">Buy on</span>
                                        <span className="font-mono">{selectedOpp.buy_dex} @ {selectedOpp.buy_price.toFixed(6)}</span>
                                    </div>
                                    <div className="flex justify-between text-sm">
                                        <span className="text-white/50">Sell on</span>
                                        <span className="font-mono">{selectedOpp.sell_dex} @ {selectedOpp.sell_price.toFixed(6)}</span>
                                    </div>
                                    <div className="flex justify-between text-sm border-t border-white/10 pt-3">
                                        <span className="text-white/50">Estimated Profit</span>
                                        <span className="font-mono text-[#39FF14] font-bold">${selectedOpp.potential_profit_usd.toFixed(2)}</span>
                                    </div>
                                    <div className="flex justify-between text-sm">
                                        <span className="text-white/50">Gas Cost</span>
                                        <span className="font-mono text-[#FFD60A]">-${selectedOpp.gas_cost_usd.toFixed(2)}</span>
                                    </div>
                                    <div className="flex justify-between text-sm border-t border-white/10 pt-3">
                                        <span className="font-medium">Net Profit</span>
                                        <span className={`font-mono font-bold ${selectedOpp.net_profit_usd > 0 ? 'text-[#39FF14]' : 'text-[#FF003C]'}`}>
                                            ${selectedOpp.net_profit_usd.toFixed(2)}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            {/* Slippage Setting */}
                            <div className="space-y-3">
                                <div className="flex justify-between">
                                    <Label>Slippage Tolerance</Label>
                                    <span className="font-mono text-[#FF9F1C]">{slippage[0]}%</span>
                                </div>
                                <Slider
                                    value={slippage}
                                    onValueChange={setSlippage}
                                    max={5}
                                    min={0.1}
                                    step={0.1}
                                    className="[&_[role=slider]]:bg-[#FF9F1C]"
                                    data-testid="slippage-slider"
                                />
                                <p className="text-xs text-white/50">
                                    Transaction reverts if price changes more than this percentage.
                                </p>
                            </div>

                            {/* Warning */}
                            <div className="flex items-start gap-3 p-3 rounded-lg bg-[#FFD60A]/10 border border-[#FFD60A]/30">
                                <AlertCircle className="w-5 h-5 text-[#FFD60A] flex-shrink-0 mt-0.5" />
                                <p className="text-xs text-[#FFD60A]/90">
                                    Prices are verified on-chain before execution. Trade will be rejected if no longer profitable.
                                </p>
                            </div>

                            <DialogFooter className="gap-3">
                                <Button 
                                    variant="outline" 
                                    onClick={closeModal}
                                    className="border-white/20"
                                    data-testid="cancel-trade-btn"
                                    disabled={executing}
                                >
                                    Cancel
                                </Button>
                                <Button 
                                    onClick={handleExecuteTrade}
                                    disabled={!isConnected || executing}
                                    className="btn-primary"
                                    data-testid="execute-trade-btn"
                                >
                                    {executing ? (
                                        <>
                                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                            Executing...
                                        </>
                                    ) : (
                                        <>
                                            <Zap className="w-4 h-4 mr-2" />
                                            Execute Trade
                                        </>
                                    )}
                                </Button>
                            </DialogFooter>
                        </div>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
