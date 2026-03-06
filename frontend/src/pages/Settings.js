import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
    Settings as SettingsIcon, 
    Wallet, 
    Zap, 
    Shield, 
    Bell,
    ChevronLeft,
    Save,
    RefreshCw,
    Info
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { useWallet } from '@/context/WalletContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Slider } from '@/components/ui/slider';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import axios from 'axios';

const API_URL = process.env.REACT_APP_BACKEND_URL;

export default function Settings() {
    const { account, isConnected, connect, formatAddress } = useWallet();
    const [settings, setSettings] = useState({
        min_profit_threshold: 0.5,
        max_slippage: 1.0,
        gas_multiplier: 1.2,
        auto_execute: false,
        notifications: true
    });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (account) {
            fetchSettings();
        }
    }, [account]);

    const fetchSettings = async () => {
        try {
            const res = await axios.get(`${API_URL}/api/settings/${account}`);
            setSettings(res.data);
        } catch (error) {
            console.error('Failed to fetch settings:', error);
        }
    };

    const handleSave = async () => {
        if (!account) {
            toast.error('Please connect your wallet first');
            return;
        }

        setSaving(true);
        try {
            await axios.post(`${API_URL}/api/settings/${account}`, settings);
            toast.success('Settings saved successfully!');
        } catch (error) {
            toast.error('Failed to save settings');
        } finally {
            setSaving(false);
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
                                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#FF9F1C] to-[#FFD60A] flex items-center justify-center">
                                    <SettingsIcon className="w-6 h-6 text-black" />
                                </div>
                                <div>
                                    <h1 className="text-xl font-bold tracking-tight">Settings</h1>
                                    <p className="text-xs text-white/50">Configure your bot</p>
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
                <div className="max-w-3xl mx-auto">
                    <Tabs defaultValue="trading" className="space-y-6">
                        <TabsList className="bg-white/5 border border-white/10">
                            <TabsTrigger value="trading" className="data-[state=active]:bg-[#FF9F1C] data-[state=active]:text-black">
                                Trading
                            </TabsTrigger>
                            <TabsTrigger value="risk" className="data-[state=active]:bg-[#FF9F1C] data-[state=active]:text-black">
                                Risk Management
                            </TabsTrigger>
                            <TabsTrigger value="notifications" className="data-[state=active]:bg-[#FF9F1C] data-[state=active]:text-black">
                                Notifications
                            </TabsTrigger>
                        </TabsList>

                        {/* Trading Settings */}
                        <TabsContent value="trading">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                            >
                                <Card className="glass-card" data-testid="trading-settings">
                                    <CardHeader>
                                        <CardTitle className="flex items-center gap-2">
                                            <Zap className="w-5 h-5 text-[#FF9F1C]" />
                                            Trading Configuration
                                        </CardTitle>
                                        <CardDescription>
                                            Configure how the bot executes trades
                                        </CardDescription>
                                    </CardHeader>
                                    <CardContent className="space-y-6">
                                        {/* Min Profit Threshold */}
                                        <div className="space-y-3">
                                            <div className="flex justify-between">
                                                <Label>Minimum Profit Threshold</Label>
                                                <span className="font-mono text-[#39FF14]">${settings.min_profit_threshold.toFixed(2)}</span>
                                            </div>
                                            <Slider
                                                value={[settings.min_profit_threshold]}
                                                onValueChange={([value]) => setSettings({ ...settings, min_profit_threshold: value })}
                                                max={10}
                                                min={0.1}
                                                step={0.1}
                                                className="[&_[role=slider]]:bg-[#39FF14]"
                                                data-testid="min-profit-slider"
                                            />
                                            <p className="text-xs text-white/50">
                                                Minimum net profit required before considering a trade opportunity.
                                            </p>
                                        </div>

                                        {/* Max Slippage */}
                                        <div className="space-y-3">
                                            <div className="flex justify-between">
                                                <Label>Maximum Slippage</Label>
                                                <span className="font-mono text-[#00F0FF]">{settings.max_slippage.toFixed(1)}%</span>
                                            </div>
                                            <Slider
                                                value={[settings.max_slippage]}
                                                onValueChange={([value]) => setSettings({ ...settings, max_slippage: value })}
                                                max={5}
                                                min={0.1}
                                                step={0.1}
                                                className="[&_[role=slider]]:bg-[#00F0FF]"
                                                data-testid="max-slippage-slider"
                                            />
                                            <p className="text-xs text-white/50">
                                                Maximum allowed price slippage during trade execution.
                                            </p>
                                        </div>

                                        {/* Gas Multiplier */}
                                        <div className="space-y-3">
                                            <div className="flex justify-between">
                                                <Label>Gas Price Multiplier</Label>
                                                <span className="font-mono text-[#FFD60A]">{settings.gas_multiplier.toFixed(1)}x</span>
                                            </div>
                                            <Slider
                                                value={[settings.gas_multiplier]}
                                                onValueChange={([value]) => setSettings({ ...settings, gas_multiplier: value })}
                                                max={3}
                                                min={1}
                                                step={0.1}
                                                className="[&_[role=slider]]:bg-[#FFD60A]"
                                                data-testid="gas-multiplier-slider"
                                            />
                                            <p className="text-xs text-white/50">
                                                Multiplier applied to gas price for faster transaction confirmation.
                                            </p>
                                        </div>

                                        {/* Auto Execute */}
                                        <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 border border-white/10">
                                            <div className="space-y-1">
                                                <Label>Auto Execute Trades</Label>
                                                <p className="text-xs text-white/50">
                                                    Automatically execute profitable trades when found
                                                </p>
                                            </div>
                                            <Switch
                                                checked={settings.auto_execute}
                                                onCheckedChange={(checked) => setSettings({ ...settings, auto_execute: checked })}
                                                data-testid="auto-execute-switch"
                                            />
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>
                        </TabsContent>

                        {/* Risk Management */}
                        <TabsContent value="risk">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                            >
                                <Card className="glass-card" data-testid="risk-settings">
                                    <CardHeader>
                                        <CardTitle className="flex items-center gap-2">
                                            <Shield className="w-5 h-5 text-[#00F0FF]" />
                                            Risk Management
                                        </CardTitle>
                                        <CardDescription>
                                            Configure safety limits and risk parameters
                                        </CardDescription>
                                    </CardHeader>
                                    <CardContent className="space-y-6">
                                        <div className="p-4 rounded-lg bg-[#FFD60A]/10 border border-[#FFD60A]/30 flex items-start gap-3">
                                            <Info className="w-5 h-5 text-[#FFD60A] flex-shrink-0 mt-0.5" />
                                            <div>
                                                <p className="text-sm text-[#FFD60A] font-medium">Risk Warning</p>
                                                <p className="text-xs text-[#FFD60A]/80 mt-1">
                                                    Arbitrage trading involves significant risks. Always use funds you can afford to lose 
                                                    and verify all transactions before execution.
                                                </p>
                                            </div>
                                        </div>

                                        <div className="space-y-4">
                                            <div className="space-y-2">
                                                <Label>Maximum Trade Size (USD)</Label>
                                                <Input 
                                                    type="number" 
                                                    placeholder="1000"
                                                    className="bg-black/20 border-white/10 focus:border-[#FF9F1C]"
                                                    data-testid="max-trade-size-input"
                                                />
                                            </div>

                                            <div className="space-y-2">
                                                <Label>Daily Loss Limit (USD)</Label>
                                                <Input 
                                                    type="number" 
                                                    placeholder="100"
                                                    className="bg-black/20 border-white/10 focus:border-[#FF9F1C]"
                                                    data-testid="daily-loss-limit-input"
                                                />
                                            </div>

                                            <div className="space-y-2">
                                                <Label>Maximum Concurrent Trades</Label>
                                                <Select defaultValue="1">
                                                    <SelectTrigger className="bg-black/20 border-white/10" data-testid="max-concurrent-select">
                                                        <SelectValue placeholder="Select limit" />
                                                    </SelectTrigger>
                                                    <SelectContent>
                                                        <SelectItem value="1">1 trade</SelectItem>
                                                        <SelectItem value="2">2 trades</SelectItem>
                                                        <SelectItem value="3">3 trades</SelectItem>
                                                        <SelectItem value="5">5 trades</SelectItem>
                                                    </SelectContent>
                                                </Select>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>
                        </TabsContent>

                        {/* Notifications */}
                        <TabsContent value="notifications">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                            >
                                <Card className="glass-card" data-testid="notification-settings">
                                    <CardHeader>
                                        <CardTitle className="flex items-center gap-2">
                                            <Bell className="w-5 h-5 text-[#FF9F1C]" />
                                            Notification Settings
                                        </CardTitle>
                                        <CardDescription>
                                            Configure how you receive alerts
                                        </CardDescription>
                                    </CardHeader>
                                    <CardContent className="space-y-4">
                                        <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 border border-white/10">
                                            <div className="space-y-1">
                                                <Label>Enable Notifications</Label>
                                                <p className="text-xs text-white/50">
                                                    Receive alerts for opportunities and trades
                                                </p>
                                            </div>
                                            <Switch
                                                checked={settings.notifications}
                                                onCheckedChange={(checked) => setSettings({ ...settings, notifications: checked })}
                                                data-testid="notifications-switch"
                                            />
                                        </div>

                                        <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 border border-white/10">
                                            <div className="space-y-1">
                                                <Label>High Profit Alerts</Label>
                                                <p className="text-xs text-white/50">
                                                    Alert when profit exceeds threshold
                                                </p>
                                            </div>
                                            <Switch defaultChecked data-testid="high-profit-alerts-switch" />
                                        </div>

                                        <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 border border-white/10">
                                            <div className="space-y-1">
                                                <Label>Trade Execution Alerts</Label>
                                                <p className="text-xs text-white/50">
                                                    Alert when a trade is executed
                                                </p>
                                            </div>
                                            <Switch defaultChecked data-testid="trade-alerts-switch" />
                                        </div>

                                        <div className="flex items-center justify-between p-4 rounded-lg bg-white/5 border border-white/10">
                                            <div className="space-y-1">
                                                <Label>Error Alerts</Label>
                                                <p className="text-xs text-white/50">
                                                    Alert when an error occurs
                                                </p>
                                            </div>
                                            <Switch defaultChecked data-testid="error-alerts-switch" />
                                        </div>
                                    </CardContent>
                                </Card>
                            </motion.div>
                        </TabsContent>
                    </Tabs>

                    {/* Save Button */}
                    <div className="mt-8 flex justify-end">
                        <Button 
                            onClick={handleSave}
                            disabled={saving || !isConnected}
                            className="btn-primary"
                            data-testid="save-settings-btn"
                        >
                            {saving ? (
                                <>
                                    <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                                    Saving...
                                </>
                            ) : (
                                <>
                                    <Save className="w-4 h-4 mr-2" />
                                    Save Settings
                                </>
                            )}
                        </Button>
                    </div>
                </div>
            </main>
        </div>
    );
}
