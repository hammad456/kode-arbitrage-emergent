import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { ethers } from 'ethers';
import { toast } from 'sonner';

const WalletContext = createContext(null);

const BERACHAIN_CONFIG = {
    chainId: '0x138de', // 80094 in hex
    chainName: 'Berachain Mainnet',
    nativeCurrency: {
        name: 'BERA',
        symbol: 'BERA',
        decimals: 18,
    },
    rpcUrls: ['https://rpc.berachain.com'],
    blockExplorerUrls: ['https://berascan.com'],
};

export function WalletProvider({ children }) {
    const [account, setAccount] = useState(null);
    const [provider, setProvider] = useState(null);
    const [signer, setSigner] = useState(null);
    const [chainId, setChainId] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [balances, setBalances] = useState({});

    const switchToBerachain = async () => {
        if (!window.ethereum) return false;

        try {
            await window.ethereum.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: BERACHAIN_CONFIG.chainId }],
            });
            return true;
        } catch (switchError) {
            if (switchError.code === 4902) {
                try {
                    await window.ethereum.request({
                        method: 'wallet_addEthereumChain',
                        params: [BERACHAIN_CONFIG],
                    });
                    return true;
                } catch (addError) {
                    console.error('Failed to add Berachain:', addError);
                    return false;
                }
            }
            console.error('Failed to switch to Berachain:', switchError);
            return false;
        }
    };

    const connect = useCallback(async () => {
        if (!window.ethereum) {
            toast.error('MetaMask not detected. Please install MetaMask.');
            return;
        }

        setIsConnecting(true);

        try {
            const web3Provider = new ethers.providers.Web3Provider(window.ethereum);
            const accounts = await window.ethereum.request({ 
                method: 'eth_requestAccounts' 
            });

            if (accounts.length === 0) {
                throw new Error('No accounts found');
            }

            const network = await web3Provider.getNetwork();
            setChainId(network.chainId);

            // Switch to Berachain if not already on it
            if (network.chainId !== 80094) {
                toast.info('Switching to Berachain...');
                const switched = await switchToBerachain();
                if (!switched) {
                    toast.error('Failed to switch to Berachain');
                    setIsConnecting(false);
                    return;
                }
            }

            const web3Signer = web3Provider.getSigner();
            
            setProvider(web3Provider);
            setSigner(web3Signer);
            setAccount(accounts[0]);
            
            toast.success('Wallet connected successfully!');
        } catch (error) {
            console.error('Connection error:', error);
            toast.error(error.message || 'Failed to connect wallet');
        } finally {
            setIsConnecting(false);
        }
    }, []);

    const disconnect = useCallback(() => {
        setAccount(null);
        setProvider(null);
        setSigner(null);
        setChainId(null);
        setBalances({});
        toast.info('Wallet disconnected');
    }, []);

    const formatAddress = useCallback((address) => {
        if (!address) return '';
        return `${address.slice(0, 6)}...${address.slice(-4)}`;
    }, []);

    // Listen for account changes
    useEffect(() => {
        if (!window.ethereum) return;

        const handleAccountsChanged = (accounts) => {
            if (accounts.length === 0) {
                disconnect();
            } else if (accounts[0] !== account) {
                setAccount(accounts[0]);
                toast.info('Account changed');
            }
        };

        const handleChainChanged = (chainId) => {
            setChainId(parseInt(chainId, 16));
            window.location.reload();
        };

        window.ethereum.on('accountsChanged', handleAccountsChanged);
        window.ethereum.on('chainChanged', handleChainChanged);

        return () => {
            window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            window.ethereum.removeListener('chainChanged', handleChainChanged);
        };
    }, [account, disconnect]);

    // Auto-connect if previously connected
    useEffect(() => {
        const checkConnection = async () => {
            if (window.ethereum) {
                const accounts = await window.ethereum.request({ 
                    method: 'eth_accounts' 
                });
                if (accounts.length > 0) {
                    connect();
                }
            }
        };
        checkConnection();
    }, [connect]);

    const value = {
        account,
        provider,
        signer,
        chainId,
        isConnecting,
        balances,
        setBalances,
        connect,
        disconnect,
        formatAddress,
        isConnected: !!account,
        isCorrectChain: chainId === 80094,
    };

    return (
        <WalletContext.Provider value={value}>
            {children}
        </WalletContext.Provider>
    );
}

export function useWallet() {
    const context = useContext(WalletContext);
    if (!context) {
        throw new Error('useWallet must be used within a WalletProvider');
    }
    return context;
}
