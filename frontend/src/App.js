import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Dashboard from "@/pages/Dashboard";
import Settings from "@/pages/Settings";
import Analytics from "@/pages/Analytics";
import { WalletProvider } from "@/context/WalletContext";

function App() {
    return (
        <WalletProvider>
            <div className="App bg-grid-pattern min-h-screen dark">
                <Toaster 
                    position="top-right" 
                    toastOptions={{
                        style: {
                            background: 'rgba(15, 17, 21, 0.95)',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            color: '#fff',
                        },
                    }}
                />
                <BrowserRouter>
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/settings" element={<Settings />} />
                        <Route path="/analytics" element={<Analytics />} />
                    </Routes>
                </BrowserRouter>
            </div>
        </WalletProvider>
    );
}

export default App;
