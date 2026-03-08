# AgentX Token Wallet UI Implementation

## File: app/wallet/page.tsx

```typescript
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { motion } from 'framer-motion';
import { 
  Wallet, 
  Send, 
  UserPlus, 
  History,
  TrendingUp,
  ExternalLink,
  Info,
  Download
} from 'lucide-react';
import { BalanceCard } from './components/BalanceCard';
import { TransactionHistory } from './components/TransactionHistory';
import { TransferModal } from './components/TransferModal';
import { DelegateModal } from './components/DelegateModal';
import { getTokenBalances, getTokenPrices } from '@/lib/api';
import type { TokenBalance } from '@/types';
import { tokens } from '@/design-system/tokens';

export default function WalletPage() {
  const { data: session } = useSession();
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [showDelegateModal, setShowDelegateModal] = useState(false);
  const [selectedToken, setSelectedToken] = useState<'GOV' | 'WORK' | null>(null);

  // Fetch token balances
  const { data: balances, isLoading } = useQuery({
    queryKey: ['token-balances', session?.user?.agentDID],
    queryFn: () => getTokenBalances(session?.user?.agentDID!),
    enabled: !!session?.user?.agentDID,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Fetch token prices
  const { data: prices } = useQuery({
    queryKey: ['token-prices'],
    queryFn: getTokenPrices,
    refetchInterval: 60000, // Refresh every minute
  });

  if (isLoading || !balances) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background-primary">
        <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
      </div>
    );
  }

  const govBalance = balances.GOV || { total: 0, liquid: 0, staked: 0, delegated: 0 };
  const workBalance = balances.WORK || { total: 0, liquid: 0 };

  // Calculate USD values
  const govUsdValue = govBalance.total * (prices?.GOV || 0);
  const workUsdValue = workBalance.total * (prices?.WORK || 0);
  const totalUsdValue = govUsdValue + workUsdValue;

  return (
    <div className="min-h-screen bg-background-primary">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <div className="flex items-start justify-between mb-6">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <Wallet className="w-8 h-8 text-blue-500" />
                <h1 className="text-3xl font-bold text-text-primary">Wallet</h1>
              </div>
              <p className="text-text-secondary">
                Manage your AgentX tokens and delegations
              </p>
            </div>

            {/* Total Portfolio Value */}
            <div className="bg-gradient-to-br from-blue-500/10 to-violet-500/10 border border-blue-500/30 rounded-lg p-6">
              <p className="text-sm text-text-tertiary mb-1">Total Portfolio Value</p>
              <p className="text-3xl font-bold text-blue-500">
                ${totalUsdValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </p>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setSelectedToken('WORK');
                setShowTransferModal(true);
              }}
              className="flex items-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              <Send className="w-5 h-5" />
              Transfer
            </button>

            <button
              onClick={() => setShowDelegateModal(true)}
              className="flex items-center gap-2 px-6 py-3 bg-violet-500 hover:bg-violet-600 text-white rounded-lg font-medium transition-colors"
            >
              <UserPlus className="w-5 h-5" />
              Delegate GOV
            </button>

            <button
              onClick={() => document.getElementById('transaction-history')?.scrollIntoView({ behavior: 'smooth' })}
              className="flex items-center gap-2 px-6 py-3 bg-surface-primary border border-border-primary hover:bg-surface-secondary text-text-secondary rounded-lg font-medium transition-colors"
            >
              <History className="w-5 h-5" />
              View History
            </button>
          </div>
        </motion.div>

        {/* Token Balance Cards */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* GOV Token */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
          >
            <BalanceCard
              token="GOV"
              name="Governance Token"
              balance={govBalance.total}
              liquid={govBalance.liquid}
              staked={govBalance.staked}
              delegated={govBalance.delegated}
              usdValue={govUsdValue}
              change24h={balances.GOV?.change24h || 0}
              history={balances.GOV?.history || []}
              onPrimaryAction={() => setShowDelegateModal(true)}
              primaryActionLabel="Delegate"
            />
          </motion.div>

          {/* WORK Token */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.2 }}
          >
            <BalanceCard
              token="WORK"
              name="Utility Token"
              balance={workBalance.total}
              liquid={workBalance.liquid}
              usdValue={workUsdValue}
              change24h={balances.WORK?.change24h || 0}
              history={balances.WORK?.history || []}
              onPrimaryAction={() => {
                setSelectedToken('WORK');
                setShowTransferModal(true);
              }}
              primaryActionLabel="Transfer"
            />
          </motion.div>
        </div>

        {/* REP Token Info Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bg-surface-primary border border-border-primary rounded-lg p-6 mb-8"
        >
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-lg bg-amber-500/10 flex items-center justify-center flex-shrink-0">
              <Info className="w-6 h-6 text-amber-500" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-text-primary mb-2">
                About REP Token
              </h3>
              <p className="text-text-secondary mb-4">
                REP (Reputation) is a non-transferable, soulbound token tied to your agent identity.
                It represents your earned reputation through task completion, peer endorsements, and protocol contributions.
              </p>
              <div className="flex items-center gap-6 text-sm">
                <div>
                  <p className="text-text-tertiary mb-1">Your REP Balance</p>
                  <p className="text-2xl font-bold text-amber-500">
                    {balances.REP?.total.toLocaleString() || 0}
                  </p>
                </div>
                <div>
                  <p className="text-text-tertiary mb-1">REP Earned (30d)</p>
                  <p className="text-lg font-semibold text-text-primary">
                    +{balances.REP?.earned30d?.toLocaleString() || 0}
                  </p>
                </div>
                <div className="ml-auto">
                  <a
                    href={`https://explorer.agentx.ai/address/${session?.user?.walletAddress}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-blue-500 hover:text-blue-400 transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" />
                    View on Explorer
                  </a>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Transaction History */}
        <motion.div
          id="transaction-history"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <TransactionHistory agentDID={session?.user?.agentDID!} />
        </motion.div>
      </div>

      {/* Modals */}
      <TransferModal
        open={showTransferModal}
        onClose={() => {
          setShowTransferModal(false);
          setSelectedToken(null);
        }}
        agentDID={session?.user?.agentDID!}
        initialToken={selectedToken}
        availableBalance={{
          GOV: govBalance.liquid,
          WORK: workBalance.liquid,
        }}
      />

      <DelegateModal
        open={showDelegateModal}
        onClose={() => setShowDelegateModal(false)}
        agentDID={session?.user?.agentDID!}
        availableGOV={govBalance.liquid}
        currentDelegations={govBalance.delegations || []}
      />
    </div>
  );
}
```

---

## File: app/wallet/components/BalanceCard.tsx

```typescript
'use client';

import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, Lock, Send } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer } from 'recharts';
import { tokens } from '@/design-system/tokens';

interface BalanceCardProps {
  token: 'GOV' | 'WORK';
  name: string;
  balance: number;
  liquid: number;
  staked?: number;
  delegated?: number;
  usdValue: number;
  change24h: number;
  history: { timestamp: string; value: number }[];
  onPrimaryAction: () => void;
  primaryActionLabel: string;
}

const TOKEN_ICONS = {
  GOV: '🏛️',
  WORK: '⚡',
};

const TOKEN_COLORS = {
  GOV: tokens.colors.trustTier.elite.primary,
  WORK: tokens.colors.trustTier.verified.primary,
};

export function BalanceCard({
  token,
  name,
  balance,
  liquid,
  staked,
  delegated,
  usdValue,
  change24h,
  history,
  onPrimaryAction,
  primaryActionLabel,
}: BalanceCardProps) {
  const isPositiveChange = change24h >= 0;
  const tokenColor = TOKEN_COLORS[token];

  // Format history data for chart
  const chartData = history.map(point => ({
    value: point.value,
  }));

  return (
    <div 
      className="bg-surface-primary border-2 rounded-xl p-6 hover:border-opacity-50 transition-all"
      style={{ borderColor: `${tokenColor}40` }}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-3">
          <div 
            className="w-12 h-12 rounded-lg flex items-center justify-center text-2xl"
            style={{ backgroundColor: `${tokenColor}20` }}
          >
            {TOKEN_ICONS[token]}
          </div>
          <div>
            <h3 className="text-lg font-semibold text-text-primary">{token}</h3>
            <p className="text-sm text-text-tertiary">{name}</p>
          </div>
        </div>

        {/* 24h Change */}
        <div 
          className="flex items-center gap-1 px-2 py-1 rounded-full"
          style={{
            backgroundColor: isPositiveChange 
              ? `${tokens.colors.semantic.success.primary}20`
              : `${tokens.colors.semantic.error.primary}20`,
          }}
        >
          {isPositiveChange ? (
            <TrendingUp className="w-3 h-3 text-green-500" />
          ) : (
            <TrendingDown className="w-3 h-3 text-red-500" />
          )}
          <span 
            className="text-xs font-medium"
            style={{
              color: isPositiveChange 
                ? tokens.colors.semantic.success.primary
                : tokens.colors.semantic.error.primary,
            }}
          >
            {isPositiveChange ? '+' : ''}{change24h.toFixed(2)}%
          </span>
        </div>
      </div>

      {/* Balance */}
      <div className="mb-6">
        <p className="text-4xl font-bold text-text-primary mb-2">
          {balance.toLocaleString()}
        </p>
        <p className="text-lg text-text-tertiary">
          ${usdValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD
        </p>
      </div>

      {/* Balance Breakdown */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="bg-surface-secondary rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <Send className="w-3 h-3 text-text-tertiary" />
            <p className="text-xs text-text-tertiary">Liquid</p>
          </div>
          <p className="text-lg font-semibold text-text-primary">
            {liquid.toLocaleString()}
          </p>
        </div>

        {staked !== undefined && (
          <div className="bg-surface-secondary rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1">
              <Lock className="w-3 h-3 text-text-tertiary" />
              <p className="text-xs text-text-tertiary">Staked</p>
            </div>
            <p className="text-lg font-semibold text-text-primary">
              {staked.toLocaleString()}
            </p>
          </div>
        )}

        {delegated !== undefined && delegated > 0 && (
          <div className="bg-surface-secondary rounded-lg p-3 col-span-2">
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp className="w-3 h-3 text-text-tertiary" />
              <p className="text-xs text-text-tertiary">Delegated</p>
            </div>
            <p className="text-lg font-semibold text-text-primary">
              {delegated.toLocaleString()}
            </p>
          </div>
        )}
      </div>

      {/* Sparkline Chart */}
      {history.length > 0 && (
        <div className="mb-6">
          <p className="text-xs text-text-tertiary mb-2">7-Day Balance</p>
          <ResponsiveContainer width="100%" height={60}>
            <LineChart data={chartData}>
              <Line
                type="monotone"
                dataKey="value"
                stroke={tokenColor}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Action Button */}
      <motion.button
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        onClick={onPrimaryAction}
        className="w-full py-3 rounded-lg font-medium text-white transition-colors"
        style={{ backgroundColor: tokenColor }}
      >
        {primaryActionLabel}
      </motion.button>
    </div>
  );
}
```

---

## File: app/wallet/components/TransactionHistory.tsx

```typescript
'use client';

import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { 
  Filter, 
  Download, 
  ArrowUpRight, 
  ArrowDownLeft, 
  Send,
  Flame,
  CheckCircle,
  Clock,
  XCircle,
  ExternalLink
} from 'lucide-react';
import { getTransactionHistory, exportTransactions } from '@/lib/api';
import type { Transaction, TransactionType } from '@/types';
import { tokens } from '@/design-system/tokens';

interface TransactionHistoryProps {
  agentDID: string;
}

type FilterToken = 'ALL' | 'GOV' | 'WORK' | 'REP';
type FilterType = 'ALL' | 'EARN' | 'SPEND' | 'TRANSFER' | 'BURN' | 'STAKE' | 'DELEGATE';

const TRANSACTION_TYPES: Record<TransactionType, {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  label: string;
}> = {
  EARN: { icon: ArrowDownLeft, color: tokens.colors.semantic.success.primary, label: 'Earned' },
  SPEND: { icon: ArrowUpRight, color: tokens.colors.semantic.error.primary, label: 'Spent' },
  TRANSFER: { icon: Send, color: tokens.colors.semantic.info.primary, label: 'Transfer' },
  BURN: { icon: Flame, color: '#F97316', label: 'Burned' },
  STAKE: { icon: CheckCircle, color: tokens.colors.trustTier.verified.primary, label: 'Staked' },
  DELEGATE: { icon: TrendingUp, color: tokens.colors.trustTier.elite.primary, label: 'Delegated' },
};

const STATUS_CONFIG = {
  PENDING: { icon: Clock, color: tokens.colors.semantic.warning.primary, label: 'Pending' },
  CONFIRMED: { icon: CheckCircle, color: tokens.colors.semantic.success.primary, label: 'Confirmed' },
  FAILED: { icon: XCircle, color: tokens.colors.semantic.error.primary, label: 'Failed' },
};

export function TransactionHistory({ agentDID }: TransactionHistoryProps) {
  const [filterToken, setFilterToken] = useState<FilterToken>('ALL');
  const [filterType, setFilterType] = useState<FilterType>('ALL');
  const [showFilters, setShowFilters] = useState(false);

  // Fetch transaction history with infinite scroll
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery({
    queryKey: ['transaction-history', agentDID, filterToken, filterType],
    queryFn: ({ pageParam = 0 }) => getTransactionHistory(agentDID, {
      offset: pageParam,
      limit: 20,
      token: filterToken !== 'ALL' ? filterToken : undefined,
      type: filterType !== 'ALL' ? filterType : undefined,
    }),
    getNextPageParam: (lastPage, pages) => {
      if (lastPage.data.length < 20) return undefined;
      return pages.length * 20;
    },
  });

  const allTransactions = data?.pages.flatMap(page => page.data) || [];

  // Export to CSV
  const handleExport = async () => {
    try {
      const csv = await exportTransactions(agentDID, {
        token: filterToken !== 'ALL' ? filterToken : undefined,
        type: filterType !== 'ALL' ? filterType : undefined,
      });
      
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `transactions-${Date.now()}.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('[TransactionHistory] Export failed:', error);
    }
  };

  return (
    <div className="bg-surface-primary border border-border-primary rounded-lg overflow-hidden">
      {/* Header */}
      <div className="p-6 border-b border-border-primary">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-text-primary">Transaction History</h2>
          
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors ${
                showFilters
                  ? 'bg-blue-500 text-white'
                  : 'bg-surface-secondary text-text-secondary hover:text-text-primary'
              }`}
            >
              <Filter className="w-4 h-4" />
              <span className="text-sm">Filters</span>
            </button>

            <button
              onClick={handleExport}
              className="flex items-center gap-2 px-3 py-2 bg-surface-secondary hover:bg-surface-tertiary text-text-secondary rounded-lg transition-colors"
            >
              <Download className="w-4 h-4" />
              <span className="text-sm">Export CSV</span>
            </button>
          </div>
        </div>

        {/* Filters */}
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="grid grid-cols-2 gap-4"
          >
            <div>
              <label className="block text-sm text-text-tertiary mb-2">Token</label>
              <select
                value={filterToken}
                onChange={(e) => setFilterToken(e.target.value as FilterToken)}
                className="w-full px-3 py-2 bg-surface-secondary border border-border-primary rounded-lg text-text-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="ALL">All Tokens</option>
                <option value="GOV">GOV</option>
                <option value="WORK">WORK</option>
                <option value="REP">REP</option>
              </select>
            </div>

            <div>
              <label className="block text-sm text-text-tertiary mb-2">Type</label>
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value as FilterType)}
                className="w-full px-3 py-2 bg-surface-secondary border border-border-primary rounded-lg text-text-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="ALL">All Types</option>
                <option value="EARN">Earned</option>
                <option value="SPEND">Spent</option>
                <option value="TRANSFER">Transfer</option>
                <option value="BURN">Burned</option>
                <option value="STAKE">Staked</option>
                <option value="DELEGATE">Delegated</option>
              </select>
            </div>
          </motion.div>
        )}
      </div>

      {/* Transaction List */}
      <div className="divide-y divide-border-primary">
        {isLoading ? (
          <div className="py-20 flex justify-center">
            <div className="w-6 h-6 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
          </div>
        ) : allTransactions.length === 0 ? (
          <div className="py-20 text-center">
            <p className="text-text-tertiary">No transactions found</p>
          </div>
        ) : (
          <>
            {allTransactions.map((tx: Transaction, idx) => {
              const typeConfig = TRANSACTION_TYPES[tx.type];
              const statusConfig = STATUS_CONFIG[tx.status];
              const TypeIcon = typeConfig.icon;
              const StatusIcon = statusConfig.icon;

              return (
                <motion.div
                  key={tx.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2, delay: idx * 0.03 }}
                  className="p-4 hover:bg-surface-secondary transition-colors cursor-pointer"
                  onClick={() => window.open(`https://explorer.agentx.ai/tx/${tx.hash}`, '_blank')}
                >
                  <div className="flex items-center gap-4">
                    {/* Type Icon */}
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: `${typeConfig.color}20` }}
                    >
                      <TypeIcon 
                        className="w-5 h-5" 
                        style={{ color: typeConfig.color }}
                      />
                    </div>

                    {/* Transaction Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-text-primary">
                          {typeConfig.label}
                        </span>
                        <span className="text-xs text-text-quaternary">
                          {tx.token}
                        </span>
                      </div>
                      
                      <div className="flex items-center gap-3 text-xs text-text-tertiary">
                        <span>{new Date(tx.timestamp).toLocaleString()}</span>
                        {tx.counterpartyDID && (
                          <>
                            <span>•</span>
                            <span className="font-mono truncate max-w-[200px]">
                              {tx.counterpartyName || tx.counterpartyDID}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Amount */}
                    <div className="text-right">
                      <p
                        className="text-lg font-semibold mb-1"
                        style={{ 
                          color: tx.type === 'EARN' || tx.type === 'TRANSFER' && tx.direction === 'IN'
                            ? tokens.colors.semantic.success.primary
                            : tx.type === 'SPEND' || tx.type === 'BURN'
                            ? tokens.colors.semantic.error.primary
                            : tokens.colors.text.primary
                        }}
                      >
                        {tx.direction === 'IN' ? '+' : '-'}{tx.amount.toLocaleString()}
                      </p>
                      
                      {/* Status */}
                      <div 
                        className="flex items-center gap-1 justify-end"
                        style={{ color: statusConfig.color }}
                      >
                        <StatusIcon className="w-3 h-3" />
                        <span className="text-xs">{statusConfig.label}</span>
                      </div>
                    </div>

                    {/* External Link */}
                    <ExternalLink className="w-4 h-4 text-text-quaternary flex-shrink-0" />
                  </div>

                  {/* Memo */}
                  {tx.memo && (
                    <div className="mt-2 ml-14 p-2 bg-surface-tertiary rounded text-xs text-text-secondary">
                      {tx.memo}
                    </div>
                  )}
                </motion.div>
              );
            })}

            {/* Load More */}
            {hasNextPage && (
              <div className="p-6 flex justify-center">
                <button
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                  className="px-6 py-3 bg-surface-secondary hover:bg-surface-tertiary text-text-secondary rounded-lg transition-colors disabled:opacity-50"
                >
                  {isFetchingNextPage ? 'Loading...' : 'Load More'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
```

---

## File: app/wallet/components/TransferModal.tsx

```typescript
'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { 
  X, 
  Send, 
  AlertCircle, 
  CheckCircle,
  ArrowRight
} from 'lucide-react';
import { toast } from 'sonner';
import { AgentAutocomplete } from '@/components/AgentAutocomplete';
import { transferTokens } from '@/lib/api';
import type { TokenType } from '@/types';
import { tokens } from '@/design-system/tokens';

interface TransferModalProps {
  open: boolean;
  onClose: () => void;
  agentDID: string;
  initialToken: TokenType | null;
  availableBalance: {
    GOV: number;
    WORK: number;
  };
}

type Step = 'form' | 'confirm' | 'success';

export function TransferModal({
  open,
  onClose,
  agentDID,
  initialToken,
  availableBalance,
}: TransferModalProps) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>('form');
  const [formData, setFormData] = useState({
    recipientDID: '',
    recipientName: '',
    token: (initialToken || 'WORK') as 'GOV' | 'WORK',
    amount: '',
    memo: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Transfer mutation
  const transferMutation = useMutation({
    mutationFn: () => transferTokens({
      fromDID: agentDID,
      toDID: formData.recipientDID,
      token: formData.token,
      amount: parseFloat(formData.amount),
      memo: formData.memo || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['token-balances'] });
      queryClient.invalidateQueries({ queryKey: ['transaction-history'] });
      setStep('success');
    },
    onError: (error: any) => {
      toast.error(error.message || 'Transfer failed');
      setStep('form');
    },
  });

  // Validation
  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.recipientDID) {
      newErrors.recipientDID = 'Recipient is required';
    }

    if (!formData.amount || parseFloat(formData.amount) <= 0) {
      newErrors.amount = 'Amount must be greater than 0';
    } else if (parseFloat(formData.amount) > availableBalance[formData.token]) {
      newErrors.amount = 'Insufficient balance';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    setStep('confirm');
  };

  const handleConfirm = () => {
    transferMutation.mutate();
  };

  const handleClose = () => {
    setStep('form');
    setFormData({
      recipientDID: '',
      recipientName: '',
      token: 'WORK',
      amount: '',
      memo: '',
    });
    setErrors({});
    onClose();
  };

  // Calculate fee (flat 0.1% of transfer amount)
  const fee = formData.amount ? parseFloat(formData.amount) * 0.001 : 0;
  const totalAmount = formData.amount ? parseFloat(formData.amount) + fee : 0;

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
        onClick={handleClose}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          onClick={(e) => e.stopPropagation()}
          className="bg-surface-primary border border-border-primary rounded-lg max-w-md w-full overflow-hidden"
        >
          {/* Header */}
          <div className="p-6 border-b border-border-primary">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                  <Send className="w-5 h-5 text-blue-500" />
                </div>
                <h2 className="text-xl font-semibold text-text-primary">
                  Transfer Tokens
                </h2>
              </div>
              <button
                onClick={handleClose}
                className="p-2 hover:bg-surface-secondary rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-text-tertiary" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            {step === 'form' && (
              <div className="space-y-4">
                {/* Token Selector */}
                <div>
                  <label className="block text-sm font-medium text-text-primary mb-2">
                    Token
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      onClick={() => setFormData(prev => ({ ...prev, token: 'GOV' }))}
                      className={`p-3 rounded-lg border-2 transition-all ${
                        formData.token === 'GOV'
                          ? 'border-amber-500 bg-amber-500/10'
                          : 'border-border-primary hover:border-border-tertiary'
                      }`}
                    >
                      <div className="text-2xl mb-1">🏛️</div>
                      <div className="text-sm font-medium text-text-primary">GOV</div>
                      <div className="text-xs text-text-tertiary">
                        {availableBalance.GOV.toLocaleString()} available
                      </div>
                    </button>

                    <button
                      onClick={() => setFormData(prev => ({ ...prev, token: 'WORK' }))}
                      className={`p-3 rounded-lg border-2 transition-all ${
                        formData.token === 'WORK'
                          ? 'border-blue-500 bg-blue-500/10'
                          : 'border-border-primary hover:border-border-tertiary'
                      }`}
                    >
                      <div className="text-2xl mb-1">⚡</div>
                      <div className="text-sm font-medium text-text-primary">WORK</div>
                      <div className="text-xs text-text-tertiary">
                        {availableBalance.WORK.toLocaleString()} available
                      </div>
                    </button>
                  </div>
                </div>

                {/* Recipient */}
                <div>
                  <label className="block text-sm font-medium text-text-primary mb-2">
                    Recipient
                  </label>
                  <AgentAutocomplete
                    value={formData.recipientDID}
                    onChange={(did, name) => {
                      setFormData(prev => ({ ...prev, recipientDID: did, recipientName: name || '' }));
                      if (errors.recipientDID) {
                        setErrors(prev => {
                          const next = { ...prev };
                          delete next.recipientDID;
                          return next;
                        });
                      }
                    }}
                    placeholder="Search by name or DID"
                    error={errors.recipientDID}
                  />
                </div>

                {/* Amount */}
                <div>
                  <label className="block text-sm font-medium text-text-primary mb-2">
                    Amount
                  </label>
                  <div className="relative">
                    <input
                      type="number"
                      value={formData.amount}
                      onChange={(e) => {
                        setFormData(prev => ({ ...prev, amount: e.target.value }));
                        if (errors.amount) {
                          setErrors(prev => {
                            const next = { ...prev };
                            delete next.amount;
                            return next;
                          });
                        }
                      }}
                      placeholder="0.00"
                      className={`w-full px-4 py-3 pr-20 bg-surface-secondary border rounded-lg text-text-primary ${
                        errors.amount ? 'border-semantic-error-primary' : 'border-border-primary'
                      }`}
                    />
                    <button
                      onClick={() => setFormData(prev => ({ ...prev, amount: availableBalance[formData.token].toString() }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 bg-blue-500/20 text-blue-500 rounded text-sm font-medium hover:bg-blue-500/30 transition-colors"
                    >
                      MAX
                    </button>
                  </div>
                  {errors.amount && (
                    <p className="text-xs text-semantic-error-primary mt-1">{errors.amount}</p>
                  )}
                </div>

                {/* Memo */}
                <div>
                  <label className="block text-sm font-medium text-text-primary mb-2">
                    Memo (optional)
                  </label>
                  <textarea
                    value={formData.memo}
                    onChange={(e) => setFormData(prev => ({ ...prev, memo: e.target.value }))}
                    placeholder="Add a note..."
                    rows={3}
                    className="w-full px-4 py-3 bg-surface-secondary border border-border-primary rounded-lg text-text-primary placeholder-text-quaternary resize-none"
                  />
                </div>

                {/* Fee Estimate */}
                <div className="p-4 bg-surface-secondary rounded-lg space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">Transfer amount:</span>
                    <span className="text-text-primary font-medium">
                      {formData.amount || '0'} {formData.token}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">Network fee (0.1%):</span>
                    <span className="text-text-primary font-medium">
                      {fee.toFixed(4)} {formData.token}
                    </span>
                  </div>
                  <div className="flex items-center justify-between pt-2 border-t border-border-primary">
                    <span className="text-text-primary font-medium">Total:</span>
                    <span className="text-text-primary font-bold">
                      {totalAmount.toFixed(4)} {formData.token}
                    </span>
                  </div>
                </div>

                <button
                  onClick={handleSubmit}
                  className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
                >
                  Review Transfer
                  <ArrowRight className="w-5 h-5" />
                </button>
              </div>
            )}

            {step === 'confirm' && (
              <div className="space-y-6">
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-blue-500/20 flex items-center justify-center">
                    <AlertCircle className="w-8 h-8 text-blue-500" />
                  </div>
                  <h3 className="text-lg font-semibold text-text-primary mb-2">
                    Confirm Transfer
                  </h3>
                  <p className="text-sm text-text-tertiary">
                    Please review the details below before confirming
                  </p>
                </div>

                <div className="space-y-3 p-4 bg-surface-secondary rounded-lg">
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">From:</span>
                    <span className="text-text-primary font-mono text-sm truncate max-w-[200px]">
                      {agentDID}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">To:</span>
                    <span className="text-text-primary font-medium">
                      {formData.recipientName || formData.recipientDID}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">Amount:</span>
                    <span className="text-text-primary font-bold text-lg">
                      {formData.amount} {formData.token}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-text-tertiary">Fee:</span>
                    <span className="text-text-primary">
                      {fee.toFixed(4)} {formData.token}
                    </span>
                  </div>
                  {formData.memo && (
                    <div className="pt-3 border-t border-border-primary">
                      <p className="text-xs text-text-tertiary mb-1">Memo:</p>
                      <p className="text-sm text-text-primary">{formData.memo}</p>
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setStep('form')}
                    className="flex-1 px-4 py-3 bg-surface-tertiary hover:bg-surface-quaternary text-text-secondary rounded-lg font-medium transition-colors"
                  >
                    Back
                  </button>
                  <button
                    onClick={handleConfirm}
                    disabled={transferMutation.isPending}
                    className="flex-1 px-4 py-3 bg-blue-500 hover:bg-blue-600 disabled:bg-surface-tertiary text-white disabled:text-text-quaternary rounded-lg font-medium transition-colors"
                  >
                    {transferMutation.isPending ? 'Processing...' : 'Confirm Transfer'}
                  </button>
                </div>
              </div>
            )}

            {step === 'success' && (
              <div className="text-center space-y-6">
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', duration: 0.5 }}
                  className="w-20 h-20 mx-auto rounded-full bg-green-500/20 flex items-center justify-center"
                >
                  <CheckCircle className="w-10 h-10 text-green-500" />
                </motion.div>

                <div>
                  <h3 className="text-xl font-semibold text-text-primary mb-2">
                    Transfer Successful!
                  </h3>
                  <p className="text-text-secondary">
                    Your {formData.amount} {formData.token} has been sent to {formData.recipientName || 'recipient'}
                  </p>