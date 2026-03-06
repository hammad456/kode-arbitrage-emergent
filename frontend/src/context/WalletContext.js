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

const ERC20_ABI = [
    "function balanceOf(address owner) view returns (uint256)",
    "function decimals() view returns (uint8)",
    "function symbol() view returns (string)",
    "function approve(address spender, uint256 amount) returns (bool)",
    "function allowance(address owner, address spender) view returns (uint256)"
];

const TOKENS = {
    BERA: { address: 'native', decimals: 18 },
    HONEY: { address: '0xFCBD14DC51f0A4d49d5E53C2E0950e0bC26d0Dce', decimals: 18 },
    WBERA: { address: '0x6969696969696969696969696969696969696969', decimals: 18 },
};

export function WalletProvider({ children }) {
    const [account, setAccount] = useState(null);
    const [provider, setProvider] = useState(null);
    const [signer, setSigner] = useState(null);
    const [chainId, setChainId] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [balances, setBalances] = useState({
        BERA: '0',
        HONEY: '0'
    });

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

    const fetchBalances = useCallback(async (web3Provider, userAddress) => {
        if (!web3Provider || !userAddress) return;

        try {
            // Get native BERA balance
            const beraBalance = await web3Provider.getBalance(userAddress);
            const beraFormatted = ethers.utils.formatEther(beraBalance);

            // Get HONEY balance
            let honeyFormatted = '0';
            try {
                const honeyContract = new ethers.Contract(
                    TOKENS.HONEY.address,
                    ERC20_ABI,
                    web3Provider
                );
                const honeyBalance = await honeyContract.balanceOf(userAddress);
                honeyFormatted = ethers.utils.formatUnits(honeyBalance, TOKENS.HONEY.decimals);
            } catch (e) {
                console.error('Failed to fetch HONEY balance:', e);
            }

            setBalances({
                BERA: beraFormatted,
                HONEY: honeyFormatted
            });
        } catch (error) {
            console.error('Failed to fetch balances:', error);
        }
    }, []);

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
                // Re-create provider after network switch
                const newProvider = new ethers.providers.Web3Provider(window.ethereum);
                const newNetwork = await newProvider.getNetwork();
                setChainId(newNetwork.chainId);
                setProvider(newProvider);
                setSigner(newProvider.getSigner());
                setAccount(accounts[0]);
                await fetchBalances(newProvider, accounts[0]);
            } else {
                const web3Signer = web3Provider.getSigner();
                setProvider(web3Provider);
                setSigner(web3Signer);
                setAccount(accounts[0]);
                await fetchBalances(web3Provider, accounts[0]);
            }
            
            toast.success('Wallet connected successfully!');
        } catch (error) {
            console.error('Connection error:', error);
            toast.error(error.message || 'Failed to connect wallet');
        } finally {
            setIsConnecting(false);
        }
    }, [fetchBalances]);

    const disconnect = useCallback(() => {
        setAccount(null);
        setProvider(null);
        setSigner(null);
        setChainId(null);
        setBalances({ BERA: '0', HONEY: '0' });
        toast.info('Wallet disconnected');
    }, []);

    const formatAddress = useCallback((address) => {
        if (!address) return '';
        return `${address.slice(0, 6)}...${address.slice(-4)}`;
    }, []);

    const refreshBalances = useCallback(async () => {
        if (provider && account) {
            await fetchBalances(provider, account);
        }
    }, [provider, account, fetchBalances]);

    const checkAllowance = useCallback(async (tokenAddress, spenderAddress) => {
        if (!provider || !account) return '0';
        
        try {
            const tokenContract = new ethers.Contract(tokenAddress, ERC20_ABI, provider);
            const allowance = await tokenContract.allowance(account, spenderAddress);
            return allowance.toString();
        } catch (error) {
            console.error('Failed to check allowance:', error);
            return '0';
        }
    }, [provider, account]);

    const approveToken = useCallback(async (tokenAddress, spenderAddress, amount) => {
        if (!signer) {
            toast.error('Wallet not connected');
            return null;
        }

        try {
            const tokenContract = new ethers.Contract(tokenAddress, ERC20_ABI, signer);
            const tx = await tokenContract.approve(spenderAddress, amount);
            toast.info('Approval transaction submitted...');
            const receipt = await tx.wait();
            toast.success('Token approved successfully!');
            return receipt;
        } catch (error) {
            console.error('Approval error:', error);
            toast.error('Failed to approve token: ' + (error.message || 'Unknown error'));
            return null;
        }
    }, [signer]);

    const executeTrade = useCallback(async (transaction) => {
        if (!signer) {
            toast.error('Wallet not connected');
            return { success: false, error: 'Wallet not connected' };
        }

        try {
            // Prepare transaction
            const tx = {
                to: transaction.to,
                data: transaction.data,
                value: transaction.value || '0x0',
                gasLimit: transaction.gas,
                gasPrice: transaction.gasPrice,
                chainId: parseInt(transaction.chainId, 16)
            };

            toast.info('Please confirm the transaction in MetaMask...');
            
            // Send transaction
            const txResponse = await signer.sendTransaction(tx);
            toast.info(`Transaction submitted: ${txResponse.hash.slice(0, 10)}...`);
            
            // Wait for confirmation
            const receipt = await txResponse.wait();
            
            if (receipt.status === 1) {
                toast.success('Trade executed successfully!');
                // Refresh balances after trade
                await refreshBalances();
                return {
                    success: true,
                    tx_hash: receipt.transactionHash,
                    gas_used: receipt.gasUsed.toString(),
                    block_number: receipt.blockNumber
                };
            } else {
                toast.error('Transaction failed');
                return { success: false, error: 'Transaction reverted' };
            }
        } catch (error) {
            console.error('Trade execution error:', error);
            
            // Handle user rejection
            if (error.code === 4001 || error.code === 'ACTION_REJECTED') {
                toast.error('Transaction rejected by user');
                return { success: false, error: 'User rejected transaction' };
            }
            
            toast.error('Trade failed: ' + (error.reason || error.message || 'Unknown error'));
            return { success: false, error: error.message || 'Unknown error' };
        }
    }, [signer, refreshBalances]);

    const signMessage = useCallback(async (message) => {
        if (!signer) {
            toast.error('Wallet not connected');
            return null;
        }

        try {
            const signature = await signer.signMessage(message);
            return signature;
        } catch (error) {
            console.error('Signing error:', error);
            toast.error('Failed to sign message');
            return null;
        }
    }, [signer]);

    // Listen for account changes
    useEffect(() => {
        if (!window.ethereum) return;

        const handleAccountsChanged = (accounts) => {
            if (accounts.length === 0) {
                disconnect();
            } else if (accounts[0] !== account) {
                setAccount(accounts[0]);
                if (provider) {
                    fetchBalances(provider, accounts[0]);
                }
                toast.info('Account changed');
            }
        };

        const handleChainChanged = (newChainId) => {
            setChainId(parseInt(newChainId, 16));
            if (parseInt(newChainId, 16) !== 80094) {
                toast.warning('Please switch to Berachain network');
            }
            window.location.reload();
        };

        window.ethereum.on('accountsChanged', handleAccountsChanged);
        window.ethereum.on('chainChanged', handleChainChanged);

        return () => {
            window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            window.ethereum.removeListener('chainChanged', handleChainChanged);
        };
    }, [account, provider, disconnect, fetchBalances]);

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

    // Periodically refresh balances
    useEffect(() => {
        if (!provider || !account) return;

        const interval = setInterval(() => {
            fetchBalances(provider, account);
        }, 30000); // Every 30 seconds

        return () => clearInterval(interval);
    }, [provider, account, fetchBalances]);

    const value = {
        account,
        provider,
        signer,
        chainId,
        isConnecting,
        balances,
        connect,
        disconnect,
        formatAddress,
        refreshBalances,
        checkAllowance,
        approveToken,
        executeTrade,
        signMessage,
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
