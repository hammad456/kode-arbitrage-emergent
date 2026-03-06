import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
    BarChart3, 
    Wallet, 
    TrendingUp,
    TrendingDown,
    ChevronLeft,
    Calendar,
    ArrowUpRight,
    ArrowDownRight,
    Clock,
    Zap
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useWallet } from '@/context/WalletContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { 
    LineChart, 
    Line, 
    XAxis, 
    YAxis, 
    CartesianGrid, 
    Tooltip, 
    ResponsiveContainer,
    AreaChart,
    Area,
    BarChart,
    Bar
} from 'recharts';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL;

// Mock chart data for demonstration
const generateChartData = () => {
    const data = [];
    const now = new Date();
    for (let i = 30; i >= 0; i--) {
        const date = new Date(now);
        date.setDate(date.getDate() - i);
        data.push({
            date: date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            profit: Math.random() * 50 - 10,
            volume: Math.random() * 1000,
            trades: Math.floor(Math.random() * 10)
        });
    }
    return data;
};

const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        return (
            <div className="custom-tooltip">
                <p className="text-sm font-medium mb-2">{label}</p>
                {payload.map((entry, index) => (
                    <p key={index} className="text-xs" style={{ color: entry.color }}>
                        {entry.name}: {typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value}
                    </p>
                ))}
            </div>
        );
    }
    return null;
};

export default function Analytics() {
    const { account, isConnected, connect, formatAddress } = useWallet();
    const [analytics, setAnalytics] = useState(null);
    const [trades, setTrades] = useState([]);
    const [loading, setLoading] = useState(true);
    const [chartData] = useState(generateChartData());

    useEffect(() => {
        if (account) {
            fetchAnalytics();
            fetchTrades();
        } else {
            setLoading(false);
        }
    }, [account]);

    const fetchAnalytics = async () => {
        try {
            const res = await axios.get(`${API_URL}/api/analytics/${account}`);
            setAnalytics(res.data);
        } catch (error) {
            console.error('Failed to fetch analytics:', error);
        }
    };

    const fetchTrades = async () => {
        try {
            const res = await axios.get(`${API_URL}/api/trades/${account}`);
            setTrades(res.data);
        } catch (error) {
            console.error('Failed to fetch trades:', error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-[#050505]">
            {/* Header */}
            <header className="header-gradient sticky top-0 z-50 border-b border-white/10">
                <div className="container mx-auto px-4 py-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                            <Link to="/" className="flex items-center gap-2 text-white/60 hover:text-white transition-colors">
                                <ChevronLeft className="w-5 h-5" />
                                Back
                            </Link>
                            <div className="h-6 w-px bg-white/20" />
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#00F0FF] to-[#00F0FF]/50 flex items-center justify-center">
                                    <BarChart3 className="w-6 h-6 text-black" />
                                </div>
                                <div>
                                    <h1 className="text-xl font-bold tracking-tight">Analytics</h1>
                                    <p className="text-xs text-white/50">Performance metrics</p>
                                </div>
                            </div>
                        </div>

                        {isConnected ? (
                            <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 border border-white/10">
                                <div className="live-indicator" />
                                <span className="font-mono text-sm">{formatAddress(account)}</span>
                            </div>
                        ) : (
                            <Button onClick={connect} className="wallet-btn">
                                <Wallet className="w-4 h-4 mr-2" />
                                Connect Wallet
                            </Button>
                        )}
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="container mx-auto px-4 py-8">
                {!isConnected ? (
                    <div className="flex flex-col items-center justify-center py-20">
                        <Wallet className="w-16 h-16 text-white/30 mb-6" />
                        <h2 className="text-2xl font-bold mb-2">Connect Your Wallet</h2>
                        <p className="text-white/50 mb-6">Connect your wallet to view your trading analytics</p>
                        <Button onClick={connect} className="btn-primary">
                            <Wallet className="w-4 h-4 mr-2" />
                            Connect Wallet
                        </Button>
                    </div>
                ) : (
                    <>
                        {/* Stats Row */}
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.1 }}
                            >
                                <Card className="stat-card success" data-testid="total-profit-stat">
                                    <CardContent className="p-6">
                                        <p className="label-text mb-1">Total Profit</p>
                                        <p className="value-large text-[#39FF14]">
                                            ${analytics?.total_profit_usd?.toFixed(2) || '0.00'}
                                        </p>
                                        <div className="flex items-center gap-1 mt-2 text-xs text-[#39FF14]">
                                            <ArrowUpRight className="w-3 h-3" />
                                            <span>+12.5% this week</span>
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>

                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.2 }}
                            >
                                <Card className="stat-card" data-testid="total-trades-stat">
                                    <CardContent className="p-6">
                                        <p className="label-text mb-1">Total Trades</p>
                                        <p className="value-large text-[#FF9F1C]">
                                            {analytics?.total_trades || 0}
                                        </p>
                                        <div className="flex items-center gap-1 mt-2 text-xs text-white/50">
                                            <Zap className="w-3 h-3" />
                                            <span>{analytics?.successful_trades || 0} successful</span>
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>

                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.3 }}
                            >
                                <Card className="stat-card secondary" data-testid="success-rate-stat">
                                    <CardContent className="p-6">
                                        <p className="label-text mb-1">Success Rate</p>
                                        <p className="value-large text-[#00F0FF]">
                                            {analytics?.success_rate?.toFixed(1) || '0'}%
                                        </p>
                                        <div className="flex items-center gap-1 mt-2 text-xs text-white/50">
                                            <TrendingUp className="w-3 h-3" />
                                            <span>Target: 95%</span>
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>

                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: 0.4 }}
                            >
                                <Card className="glass-card" data-testid="avg-profit-stat">
                                    <CardContent className="p-6">
                                        <p className="label-text mb-1">Avg Profit/Trade</p>
                                        <p className="value-large text-white">
                                            ${analytics?.average_profit_per_trade?.toFixed(2) || '0.00'}
                                        </p>
                                        <div className="flex items-center gap-1 mt-2 text-xs text-white/50">
                                            <Clock className="w-3 h-3" />
                                            <span>Last 30 days</span>
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>
                        </div>

                        {/* Charts */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                            <Card className="glass-card" data-testid="profit-chart">
                                <CardHeader>
                                    <CardTitle className="text-lg">Profit Over Time</CardTitle>
                                    <CardDescription>Daily profit/loss in USD</CardDescription>
                                </CardHeader>
                                <CardContent>
                                    <div className="h-[300px]">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <AreaChart data={chartData}>
                                                <defs>
                                                    <linearGradient id="profitGradient" x1="0" y1="0" x2="0" y2="1">
                                                        <stop offset="5%" stopColor="#39FF14" stopOpacity={0.3}/>
                                                        <stop offset="95%" stopColor="#39FF14" stopOpacity={0}/>
                                                    </linearGradient>
                                                </defs>
                                                <XAxis 
                                                    dataKey="date" 
                                                    stroke="#ffffff30"
                                                    tick={{ fill: '#ffffff50', fontSize: 11 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                />
                                                <YAxis 
                                                    stroke="#ffffff30"
                                                    tick={{ fill: '#ffffff50', fontSize: 11 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                />
                                                <Tooltip content={<CustomTooltip />} />
                                                <Area 
                                                    type="monotone" 
                                                    dataKey="profit" 
                                                    stroke="#39FF14" 
                                                    fill="url(#profitGradient)"
                                                    strokeWidth={2}
                                                    name="Profit (USD)"
                                                />
                                            </AreaChart>
                                        </ResponsiveContainer>
                                    </div>
                                </CardContent>
                            </Card>

                            <Card className="glass-card" data-testid="volume-chart">
                                <CardHeader>
                                    <CardTitle className="text-lg">Trading Volume</CardTitle>
                                    <CardDescription>Daily trading volume in USD</CardDescription>
                                </CardHeader>
                                <CardContent>
                                    <div className="h-[300px]">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <BarChart data={chartData}>
                                                <XAxis 
                                                    dataKey="date" 
                                                    stroke="#ffffff30"
                                                    tick={{ fill: '#ffffff50', fontSize: 11 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                />
                                                <YAxis 
                                                    stroke="#ffffff30"
                                                    tick={{ fill: '#ffffff50', fontSize: 11 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                />
                                                <Tooltip content={<CustomTooltip />} />
                                                <Bar 
                                                    dataKey="volume" 
                                                    fill="#FF9F1C"
                                                    radius={[4, 4, 0, 0]}
                                                    name="Volume (USD)"
                                                />
                                            </BarChart>
                                        </ResponsiveContainer>
                                    </div>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Trade History */}
                        <Card className="glass-card" data-testid="trade-history">
                            <CardHeader>
                                <CardTitle className="text-lg">Trade History</CardTitle>
                                <CardDescription>Recent arbitrage trades</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <ScrollArea className="h-[400px]">
                                    {trades.length === 0 ? (
                                        <div className="flex flex-col items-center justify-center py-16 text-white/50">
                                            <Clock className="w-12 h-12 mb-4" />
                                            <p>No trades yet</p>
                                            <p className="text-sm">Your trade history will appear here</p>
                                        </div>
                                    ) : (
                                        <table className="arb-table">
                                            <thead>
                                                <tr>
                                                    <th>Date</th>
                                                    <th>Pair</th>
                                                    <th>Route</th>
                                                    <th>Amount</th>
                                                    <th>Profit</th>
                                                    <th>Status</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {trades.map((trade) => (
                                                    <tr key={trade.id}>
                                                        <td className="text-white/60">
                                                            {new Date(trade.timestamp).toLocaleDateString()}
                                                        </td>
                                                        <td>{trade.token_pair}</td>
                                                        <td className="text-white/60">
                                                            {trade.buy_dex} → {trade.sell_dex}
                                                        </td>
                                                        <td className="font-mono">${trade.amount_in}</td>
                                                        <td className={trade.profit_usd >= 0 ? 'data-positive' : 'data-negative'}>
                                                            {trade.profit_usd >= 0 ? '+' : ''}${trade.profit_usd?.toFixed(2)}
                                                        </td>
                                                        <td>
                                                            <Badge 
                                                                variant="outline" 
                                                                className={
                                                                    trade.status === 'success' 
                                                                        ? 'bg-[#39FF14]/20 text-[#39FF14] border-[#39FF14]/30'
                                                                        : trade.status === 'pending'
                                                                        ? 'bg-[#FFD60A]/20 text-[#FFD60A] border-[#FFD60A]/30'
                                                                        : 'bg-[#FF003C]/20 text-[#FF003C] border-[#FF003C]/30'
                                                                }
                                                            >
                                                                {trade.status}
                                                            </Badge>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    )}
                                </ScrollArea>
                            </CardContent>
                        </Card>
                    </>
                )}
            </main>
        </div>
    );
}
