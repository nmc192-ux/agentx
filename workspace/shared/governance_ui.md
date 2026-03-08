# AgentX Governance Voting Interface Implementation

## File: app/governance/page.tsx

```typescript
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { 
  Vote, 
  Plus, 
  Filter,
  TrendingUp,
  Clock,
  CheckCircle,
  XCircle,
  DollarSign,
  History,
  AlertCircle
} from 'lucide-react';
import { ProposalCard } from '@/components/ProposalCard';
import { TokenBalance } from '@/components/TokenBalance';
import { getProposals, getMyVotes, getTokenBalance } from '@/lib/api';
import type { Proposal, Vote as VoteType } from '@/types';
import { tokens } from '@/design-system/tokens';

type ProposalFilter = 'all' | 'active' | 'passed' | 'rejected' | 'executed';
type Tab = 'proposals' | 'my-votes';

export default function GovernancePage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('proposals');
  const [filter, setFilter] = useState<ProposalFilter>('active');

  // Fetch active proposals
  const { data: proposals, isLoading: proposalsLoading } = useQuery({
    queryKey: ['proposals', filter],
    queryFn: () => getProposals({
      status: filter === 'all' ? undefined : filter.toUpperCase(),
      limit: 50,
    }),
    refetchInterval: 10000, // Refresh every 10 seconds for live updates
  });

  // Fetch user's vote history
  const { data: myVotes } = useQuery({
    queryKey: ['my-votes', session?.user?.agentDID],
    queryFn: () => getMyVotes(session?.user?.agentDID!),
    enabled: !!session?.user?.agentDID && tab === 'my-votes',
  });

  // Fetch GOV token balance
  const { data: govBalance } = useQuery({
    queryKey: ['token-balance', session?.user?.agentDID, 'GOV'],
    queryFn: () => getTokenBalance(session?.user?.agentDID!, 'GOV'),
    enabled: !!session?.user?.agentDID,
  });

  // Calculate voting power
  const votingPower = govBalance?.staked || 0;
  const canCreateProposal = votingPower >= 1000; // Min 1000 GOV staked

  // Calculate stats
  const stats = {
    active: proposals?.data.filter(p => p.status === 'VOTING').length || 0,
    passed: proposals?.data.filter(p => p.status === 'PASSED').length || 0,
    total: proposals?.total || 0,
  };

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
                <Vote className="w-8 h-8 text-blue-500" />
                <h1 className="text-3xl font-bold text-text-primary">
                  Governance
                </h1>
              </div>
              <p className="text-text-secondary">
                Participate in platform governance through transparent, on-chain voting
              </p>
            </div>

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => router.push('/governance/create')}
              disabled={!canCreateProposal}
              className="flex items-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 disabled:bg-surface-tertiary text-white disabled:text-text-quaternary rounded-lg font-medium transition-colors"
              title={!canCreateProposal ? 'Requires 1000 GOV staked' : ''}
            >
              <Plus className="w-5 h-5" />
              Create Proposal
            </motion.button>
          </div>

          {/* Stats + Voting Power */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            {/* Voting Power Card */}
            <div className="bg-gradient-to-br from-blue-500/10 to-violet-500/10 border border-blue-500/30 rounded-lg p-6">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <p className="text-sm text-text-tertiary mb-1">Your Voting Power</p>
                  <p className="text-3xl font-bold text-blue-500">
                    {votingPower.toLocaleString()}
                  </p>
                </div>
                <div className="w-12 h-12 rounded-lg bg-blue-500/20 flex items-center justify-center">
                  <DollarSign className="w-6 h-6 text-blue-500" />
                </div>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Total GOV</span>
                  <span className="text-text-primary font-medium">
                    {(govBalance?.total || 0).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Staked</span>
                  <span className="text-text-primary font-medium">
                    {(govBalance?.staked || 0).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Liquid</span>
                  <span className="text-text-primary font-medium">
                    {(govBalance?.liquid || 0).toLocaleString()}
                  </span>
                </div>
              </div>
            </div>

            {/* Active Proposals */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-lg bg-green-500/10 flex items-center justify-center">
                  <TrendingUp className="w-5 h-5 text-green-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.active}</p>
                  <p className="text-sm text-text-tertiary">Active Votes</p>
                </div>
              </div>
            </div>

            {/* Passed Proposals */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-blue-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.passed}</p>
                  <p className="text-sm text-text-tertiary">Passed</p>
                </div>
              </div>
            </div>

            {/* Total Proposals */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-10 h-10 rounded-lg bg-violet-500/10 flex items-center justify-center">
                  <Vote className="w-5 h-5 text-violet-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.total}</p>
                  <p className="text-sm text-text-tertiary">Total Proposals</p>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Tabs */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2 bg-surface-primary border border-border-primary rounded-lg p-1">
            <button
              onClick={() => setTab('proposals')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === 'proposals'
                  ? 'bg-blue-500 text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              All Proposals
            </button>
            <button
              onClick={() => setTab('my-votes')}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === 'my-votes'
                  ? 'bg-blue-500 text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <History className="w-4 h-4" />
              My Votes
            </button>
          </div>

          {/* Filter (only for proposals tab) */}
          {tab === 'proposals' && (
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-text-tertiary" />
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as ProposalFilter)}
                className="px-3 py-2 bg-surface-secondary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">All Status</option>
                <option value="active">Active</option>
                <option value="passed">Passed</option>
                <option value="rejected">Rejected</option>
                <option value="executed">Executed</option>
              </select>
            </div>
          )}
        </div>

        {/* Content */}
        {tab === 'proposals' ? (
          proposalsLoading ? (
            <div className="py-20 flex justify-center">
              <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
            </div>
          ) : proposals?.data.length === 0 ? (
            <div className="py-20 text-center space-y-4">
              <div className="w-16 h-16 mx-auto rounded-full bg-surface-tertiary flex items-center justify-center">
                <Vote className="w-8 h-8 text-text-quaternary" />
              </div>
              <div className="space-y-2">
                <p className="text-text-secondary font-medium">No proposals found</p>
                <p className="text-sm text-text-tertiary">
                  {filter === 'active' 
                    ? 'There are no active proposals at the moment'
                    : 'Try adjusting your filter'}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {proposals.data.map((proposal: Proposal, idx) => (
                <motion.div
                  key={proposal.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: idx * 0.05 }}
                >
                  <ProposalCard 
                    proposal={proposal}
                    votingPower={votingPower}
                    onClick={() => router.push(`/governance/${proposal.id}`)}
                  />
                </motion.div>
              ))}
            </div>
          )
        ) : (
          // My Votes Tab
          <div className="space-y-4">
            {myVotes?.length === 0 ? (
              <div className="py-20 text-center space-y-4">
                <div className="w-16 h-16 mx-auto rounded-full bg-surface-tertiary flex items-center justify-center">
                  <History className="w-8 h-8 text-text-quaternary" />
                </div>
                <div className="space-y-2">
                  <p className="text-text-secondary font-medium">No votes yet</p>
                  <p className="text-sm text-text-tertiary">
                    Start participating in governance by voting on active proposals
                  </p>
                </div>
              </div>
            ) : (
              myVotes?.map((vote: VoteType, idx) => (
                <motion.div
                  key={vote.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: idx * 0.05 }}
                  onClick={() => router.push(`/governance/${vote.proposalId}`)}
                  className="bg-surface-primary border border-border-primary hover:border-blue-500/50 rounded-lg p-6 cursor-pointer transition-all"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex-1">
                      <h3 className="text-lg font-semibold text-text-primary mb-2">
                        {vote.proposalTitle}
                      </h3>
                      <p className="text-sm text-text-tertiary">
                        Proposal #{vote.proposalId.slice(0, 8)}
                      </p>
                    </div>

                    {/* Vote Badge */}
                    <div
                      className="px-3 py-1.5 rounded-full text-sm font-medium"
                      style={{
                        backgroundColor:
                          vote.choice === 'FOR'
                            ? `${tokens.colors.semantic.success.primary}20`
                            : vote.choice === 'AGAINST'
                            ? `${tokens.colors.semantic.error.primary}20`
                            : `${tokens.colors.text.tertiary}20`,
                        color:
                          vote.choice === 'FOR'
                            ? tokens.colors.semantic.success.primary
                            : vote.choice === 'AGAINST'
                            ? tokens.colors.semantic.error.primary
                            : tokens.colors.text.tertiary,
                      }}
                    >
                      {vote.choice}
                    </div>
                  </div>

                  <div className="flex items-center gap-6 text-sm text-text-tertiary">
                    <div className="flex items-center gap-2">
                      <DollarSign className="w-4 h-4" />
                      <span>{vote.weight.toLocaleString()} GOV</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4" />
                      <span>{new Date(vote.timestamp).toLocaleDateString()}</span>
                    </div>
                  </div>

                  {vote.comment && (
                    <div className="mt-4 p-3 bg-surface-secondary rounded-lg border border-border-primary">
                      <p className="text-sm text-text-secondary">"{vote.comment}"</p>
                    </div>
                  )}
                </motion.div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

---

## File: app/governance/[proposalId]/page.tsx

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ArrowLeft,
  Calendar,
  User,
  Clock,
  TrendingUp,
  AlertCircle,
  MessageSquare,
  ExternalLink,
  Share2
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { toast } from 'sonner';
import { VoteTally } from '../components/VoteTally';
import { ProposalTimeline } from '../components/ProposalTimeline';
import { VoterList } from '../components/VoterList';
import { useWebSocket } from '@/hooks/useWebSocket';
import { getProposal, castVote, getTokenBalance } from '@/lib/api';
import type { Proposal, VoteChoice } from '@/types';
import { tokens } from '@/design-system/tokens';

export default function ProposalDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const proposalId = params.proposalId as string;

  const [showVotePanel, setShowVotePanel] = useState(false);
  const [selectedChoice, setSelectedChoice] = useState<VoteChoice | null>(null);
  const [voteComment, setVoteComment] = useState('');

  // Fetch proposal
  const { data: proposal, isLoading } = useQuery({
    queryKey: ['proposal', proposalId],
    queryFn: () => getProposal(proposalId),
    refetchInterval: 5000, // Refresh every 5 seconds for live updates
  });

  // Fetch voting power
  const { data: govBalance } = useQuery({
    queryKey: ['token-balance', session?.user?.agentDID, 'GOV'],
    queryFn: () => getTokenBalance(session?.user?.agentDID!, 'GOV'),
    enabled: !!session?.user?.agentDID,
  });

  const votingPower = govBalance?.staked || 0;

  // WebSocket for live updates
  const { lastMessage } = useWebSocket({
    url: `${process.env.NEXT_PUBLIC_WS_URL}/governance/${proposalId}`,
    onMessage: (message) => {
      if (message.type === 'VOTE_CAST' || message.type === 'QUORUM_REACHED') {
        queryClient.invalidateQueries({ queryKey: ['proposal', proposalId] });
      }
    },
  });

  // Cast vote mutation
  const voteMutation = useMutation({
    mutationFn: (data: { choice: VoteChoice; comment?: string }) =>
      castVote(proposalId, session?.user?.agentDID!, data.choice, data.comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proposal', proposalId] });
      toast.success('Vote cast successfully');
      setShowVotePanel(false);
      setSelectedChoice(null);
      setVoteComment('');
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to cast vote');
    },
  });

  if (isLoading || !proposal) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background-primary">
        <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
      </div>
    );
  }

  // Calculate time remaining
  const deadline = new Date(proposal.votingDeadline);
  const now = new Date();
  const timeRemaining = deadline.getTime() - now.getTime();
  const hasExpired = timeRemaining <= 0;
  const daysRemaining = Math.floor(timeRemaining / (1000 * 60 * 60 * 24));
  const hoursRemaining = Math.floor((timeRemaining % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));

  // Check if user has already voted
  const userVote = proposal.votes.find(v => v.voterDID === session?.user?.agentDID);
  const canVote = !userVote && !hasExpired && votingPower > 0;

  // Calculate quorum progress
  const totalVotes = proposal.votes.reduce((sum, v) => sum + v.weight, 0);
  const quorumProgress = totalVotes / proposal.quorumRequired;

  // Determine proposal outcome
  const forWeight = proposal.votes.filter(v => v.choice === 'FOR').reduce((sum, v) => sum + v.weight, 0);
  const againstWeight = proposal.votes.filter(v => v.choice === 'AGAINST').reduce((sum, v) => sum + v.weight, 0);
  const forPercentage = totalVotes > 0 ? forWeight / totalVotes : 0;
  
  const isPassing = forPercentage >= proposal.passThreshold;
  const hasQuorum = quorumProgress >= 1;

  return (
    <div className="min-h-screen bg-background-primary">
      <div className="container mx-auto px-4 py-8">
        {/* Back Button */}
        <button
          onClick={() => router.back()}
          className="flex items-center gap-2 text-text-tertiary hover:text-text-primary mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span className="text-sm">Back to Governance</span>
        </button>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Main Content */}
          <div className="lg:col-span-2 space-y-6">
            {/* Proposal Header */}
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-surface-primary border border-border-primary rounded-lg p-8"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="px-3 py-1 bg-violet-500/20 text-violet-500 text-xs font-medium uppercase tracking-wider rounded-full">
                      {proposal.proposalType}
                    </span>
                    <span
                      className="px-3 py-1 text-xs font-medium uppercase tracking-wider rounded-full"
                      style={{
                        backgroundColor: `${
                          proposal.status === 'VOTING'
                            ? tokens.colors.semantic.info.primary
                            : proposal.status === 'PASSED'
                            ? tokens.colors.semantic.success.primary
                            : tokens.colors.semantic.error.primary
                        }20`,
                        color:
                          proposal.status === 'VOTING'
                            ? tokens.colors.semantic.info.primary
                            : proposal.status === 'PASSED'
                            ? tokens.colors.semantic.success.primary
                            : tokens.colors.semantic.error.primary,
                      }}
                    >
                      {proposal.status}
                    </span>
                  </div>

                  <h1 className="text-3xl font-bold text-text-primary mb-4">
                    {proposal.title}
                  </h1>

                  <div className="flex flex-wrap items-center gap-4 text-sm text-text-tertiary">
                    <div className="flex items-center gap-2">
                      <User className="w-4 h-4" />
                      <span>{proposal.authorName}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4" />
                      <span>{new Date(proposal.createdAt).toLocaleDateString()}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4" />
                      <span>ID: {proposal.id.slice(0, 8)}</span>
                    </div>
                  </div>
                </div>

                <button
                  onClick={() => {
                    navigator.clipboard.writeText(window.location.href);
                    toast.success('Link copied to clipboard');
                  }}
                  className="p-2 hover:bg-surface-secondary rounded-lg transition-colors"
                >
                  <Share2 className="w-5 h-5 text-text-tertiary" />
                </button>
              </div>

              {/* Countdown Timer */}
              {!hasExpired && (
                <div
                  className="p-4 rounded-lg border-2 mb-6"
                  style={{
                    backgroundColor:
                      daysRemaining < 1
                        ? `${tokens.colors.semantic.error.primary}10`
                        : `${tokens.colors.semantic.info.primary}10`,
                    borderColor:
                      daysRemaining < 1
                        ? tokens.colors.semantic.error.primary
                        : tokens.colors.semantic.info.primary,
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Clock
                        className="w-6 h-6"
                        style={{
                          color:
                            daysRemaining < 1
                              ? tokens.colors.semantic.error.primary
                              : tokens.colors.semantic.info.primary,
                        }}
                      />
                      <div>
                        <p className="text-sm text-text-tertiary mb-1">Voting ends in</p>
                        <p
                          className="text-2xl font-bold"
                          style={{
                            color:
                              daysRemaining < 1
                                ? tokens.colors.semantic.error.primary
                                : tokens.colors.semantic.info.primary,
                          }}
                        >
                          {daysRemaining > 0 && `${daysRemaining}d `}
                          {hoursRemaining}h
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-text-tertiary mb-1">Deadline</p>
                      <p className="text-sm text-text-primary font-medium">
                        {deadline.toLocaleString()}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Proposal Content */}
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{proposal.content}</ReactMarkdown>
              </div>

              {/* External Links */}
              {proposal.externalLinks && proposal.externalLinks.length > 0 && (
                <div className="mt-6 pt-6 border-t border-border-primary">
                  <h3 className="text-sm font-medium text-text-tertiary mb-3">
                    Related Resources
                  </h3>
                  <div className="space-y-2">
                    {proposal.externalLinks.map((link, idx) => (
                      <a
                        key={idx}
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 text-sm text-blue-500 hover:text-blue-400 transition-colors"
                      >
                        <ExternalLink className="w-4 h-4" />
                        {link.title}
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>

            {/* Vote Tally */}
            <VoteTally
              proposal={proposal}
              onVoteReceived={() => queryClient.invalidateQueries({ queryKey: ['proposal', proposalId] })}
            />

            {/* Proposal Timeline */}
            <ProposalTimeline proposal={proposal} />

            {/* Voter List */}
            <VoterList voters={proposal.votes} totalVotingPower={totalVotes} />
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Vote Panel */}
            {canVote ? (
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                className="bg-surface-primary border-2 border-blue-500 rounded-lg p-6 space-y-4 sticky top-6"
              >
                <h2 className="text-xl font-semibold text-text-primary">Cast Your Vote</h2>

                <div className="space-y-3">
                  <button
                    onClick={() => {
                      setSelectedChoice('FOR');
                      setShowVotePanel(true);
                    }}
                    className="w-full px-4 py-3 bg-green-500/20 hover:bg-green-500/30 border-2 border-green-500 text-green-500 rounded-lg font-medium transition-colors"
                  >
                    Vote FOR
                  </button>

                  <button
                    onClick={() => {
                      setSelectedChoice('AGAINST');
                      setShowVotePanel(true);
                    }}
                    className="w-full px-4 py-3 bg-red-500/20 hover:bg-red-500/30 border-2 border-red-500 text-red-500 rounded-lg font-medium transition-colors"
                  >
                    Vote AGAINST
                  </button>

                  <button
                    onClick={() => {
                      setSelectedChoice('ABSTAIN');
                      setShowVotePanel(true);
                    }}
                    className="w-full px-4 py-3 bg-surface-tertiary hover:bg-surface-quaternary border-2 border-border-tertiary text-text-secondary rounded-lg font-medium transition-colors"
                  >
                    ABSTAIN
                  </button>
                </div>

                <div className="pt-4 border-t border-border-primary">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-text-tertiary">Your voting power:</span>
                    <span className="text-text-primary font-semibold">
                      {votingPower.toLocaleString()} GOV
                    </span>
                  </div>
                </div>

                {/* Vote Confirmation Modal */}
                <AnimatePresence>
                  {showVotePanel && selectedChoice && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
                      onClick={() => setShowVotePanel(false)}
                    >
                      <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}
                        className="bg-surface-primary border border-border-primary rounded-lg p-6 max-w-md w-full space-y-4"
                      >
                        <h3 className="text-xl font-semibold text-text-primary">
                          Confirm Vote
                        </h3>

                        <div
                          className="p-4 rounded-lg"
                          style={{
                            backgroundColor:
                              selectedChoice === 'FOR'
                                ? `${tokens.colors.semantic.success.primary}20`
                                : selectedChoice === 'AGAINST'
                                ? `${tokens.colors.semantic.error.primary}20`
                                : `${tokens.colors.text.tertiary}20`,
                          }}
                        >
                          <p className="text-sm text-text-tertiary mb-2">You are voting:</p>
                          <p
                            className="text-2xl font-bold"
                            style={{
                              color:
                                selectedChoice === 'FOR'
                                  ? tokens.colors.semantic.success.primary
                                  : selectedChoice === 'AGAINST'
                                  ? tokens.colors.semantic.error.primary
                                  : tokens.colors.text.tertiary,
                            }}
                          >
                            {selectedChoice}
                          </p>
                        </div>

                        <div className="space-y-2">
                          <label className="block text-sm text-text-tertiary">
                            Comment (optional)
                          </label>
                          <textarea
                            value={voteComment}
                            onChange={(e) => setVoteComment(e.target.value)}
                            placeholder="Explain your vote..."
                            rows={3}
                            className="w-full px-4 py-3 bg-surface-secondary border border-border-primary rounded-lg text-text-primary placeholder-text-quaternary resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div className="pt-4 border-t border-border-primary space-y-2 text-sm">
                          <div className="flex items-center justify-between">
                            <span className="text-text-tertiary">Voting power:</span>
                            <span className="text-text-primary font-medium">
                              {votingPower.toLocaleString()} GOV
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-text-quaternary">
                            <AlertCircle className="w-4 h-4" />
                            <span className="text-xs">Votes are final and cannot be changed</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <button
                            onClick={() => setShowVotePanel(false)}
                            className="flex-1 px-4 py-3 bg-surface-tertiary hover:bg-surface-quaternary text-text-secondary rounded-lg font-medium transition-colors"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => voteMutation.mutate({ choice: selectedChoice, comment: voteComment || undefined })}
                            disabled={voteMutation.isPending}
                            className="flex-1 px-4 py-3 bg-blue-500 hover:bg-blue-600 disabled:bg-surface-tertiary text-white disabled:text-text-quaternary rounded-lg font-medium transition-colors"
                          >
                            {voteMutation.isPending ? 'Casting...' : 'Confirm Vote'}
                          </button>
                        </div>
                      </motion.div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            ) : userVote ? (
              <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-4">
                <h3 className="text-lg font-semibold text-text-primary">Your Vote</h3>
                
                <div
                  className="p-4 rounded-lg"
                  style={{
                    backgroundColor:
                      userVote.choice === 'FOR'
                        ? `${tokens.colors.semantic.success.primary}20`
                        : userVote.choice === 'AGAINST'
                        ? `${tokens.colors.semantic.error.primary}20`
                        : `${tokens.colors.text.tertiary}20`,
                  }}
                >
                  <p className="text-sm text-text-tertiary mb-1">You voted:</p>
                  <p
                    className="text-2xl font-bold"
                    style={{
                      color:
                        userVote.choice === 'FOR'
                          ? tokens.colors.semantic.success.primary
                          : userVote.choice === 'AGAINST'
                          ? tokens.colors.semantic.error.primary
                          : tokens.colors.text.tertiary,
                    }}
                  >
                    {userVote.choice}
                  </p>
                </div>

                {userVote.comment && (
                  <div className="p-3 bg-surface-secondary rounded-lg border border-border-primary">
                    <p className="text-sm text-text-secondary">"{userVote.comment}"</p>
                  </div>
                )}

                <div className="flex items-center justify-between text-sm border-t border-border-primary pt-4">
                  <span className="text-text-tertiary">Voting power used:</span>
                  <span className="text-text-primary font-medium">
                    {userVote.weight.toLocaleString()} GOV
                  </span>
                </div>
              </div>
            ) : null}

            {/* Quorum Progress */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-4">
              <h3 className="text-lg font-semibold text-text-primary">Quorum Progress</h3>
              
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-tertiary">Required:</span>
                  <span className="text-text-primary font-medium">
                    {proposal.quorumRequired.toLocaleString()} GOV
                  </span>
                </div>
                
                <div className="flex items-center justify-between text-sm">
                  <span className="text-text-tertiary">Current:</span>
                  <span className="text-text-primary font-medium">
                    {totalVotes.toLocaleString()} GOV
                  </span>
                </div>

                <div className="h-2 bg-surface-tertiary rounded-full overflow-hidden">
                  <motion.div
                    className="h-full rounded-full"
                    style={{
                      backgroundColor: hasQuorum
                        ? tokens.colors.semantic.success.primary
                        : tokens.colors.semantic.warning.primary,
                    }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(quorumProgress * 100, 100)}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>

                <p className="text-sm text-text-tertiary">
                  {hasQuorum ? (
                    <span className="flex items-center gap-2 text-green-500">
                      <AlertCircle className="w-4 h-4" />
                      Quorum reached ({(quorumProgress * 100).toFixed(1)}%)
                    </span>
                  ) : (
                    `${((1 - quorumProgress) * 100).toFixed(1)}% more needed`
                  )}
                </p>
              </div>
            </div>

            {/* Outcome Prediction */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-4">
              <h3 className="text-lg font-semibold text-text-primary">Current Status</h3>
              
              <div
                className="p-4 rounded-lg"
                style={{
                  backgroundColor:
                    isPassing && hasQuorum
                      ? `${tokens.colors.semantic.success.primary}20`
                      : `${tokens.colors.semantic.error.primary}20`,
                }}
              >
                <p
                  className="text-lg font-bold"
                  style={{
                    color:
                      isPassing && hasQuorum
                        ? tokens.colors.semantic.success.primary
                        : tokens.colors.semantic.error.primary,
                  }}
                >
                  {isPassing && hasQuorum
                    ? '✓ Passing'
                    : !hasQuorum
                    ? '⚠ Quorum Not Reached'
                    : '✗ Failing'}
                </p>
              </div>

              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Pass threshold:</span>
                  <span className="text-text-primary font-medium">
                    {(proposal.passThreshold * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Current FOR:</span>
                  <span className="text-text-primary font-medium">
                    {(forPercentage * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

## File: app/governance/components/VoteTally.tsx

```typescript
'use client';

import { useEffect } from 'react';
import { motion } from 'framer-motion';
import { ThumbsUp, ThumbsDown, Minus } from 'lucide-react';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { Proposal } from '@/types';
import { tokens } from '@/design-system/tokens';

interface VoteTallyProps {
  proposal: Proposal;
  onVoteReceived?: () => void;
}

export function VoteTally({ proposal, onVoteReceived }: VoteTallyProps) {
  // Calculate vote weights
  const forWeight = proposal.votes.filter(v => v.choice === 'FOR').reduce((sum, v) => sum + v.weight, 0);
  const againstWeight = proposal.votes.filter(v => v.choice === 'AGAINST').reduce((sum, v) => sum + v.weight, 0);
  const abstainWeight = proposal.votes.filter(v => v.choice === 'ABSTAIN').reduce((sum, v) => sum + v.weight, 0);
  const totalWeight = forWeight + againstWeight + abstainWeight;

  // Calculate percentages
  const forPercentage = totalWeight > 0 ? (forWeight / totalWeight) * 100 : 0;
  const againstPercentage = totalWeight > 0 ? (againstWeight / totalWeight) * 100 : 0;
  const abstainPercentage = totalWeight > 0 ? (abstainWeight / totalWeight) * 100 : 0;

  // Calculate vote counts
  const forCount = proposal.votes.filter(v => v.choice === 'FOR').length;
  const againstCount = proposal.votes.filter(v => v.choice === 'AGAINST').length;
  const abstainCount = proposal.votes.filter(v => v.choice === 'ABSTAIN').length;

  // WebSocket for real-time updates
  const { lastMessage } = useWebSocket({
    url: `${process.env.NEXT_PUBLIC_WS_URL}/governance/${proposal.id}`,
    onMessage: (message) => {
      if (message.type === 'VOTE_CAST') {
        onVoteReceived?.();
      }
    },
  });

  return (
    <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-text-primary">Vote Tally</h2>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-sm text-text-tertiary">Live</span>
        </div>
      </div>

      {/* FOR Votes */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ThumbsUp className="w-5 h-5 text-green-500" />
            <span className="text-sm font-medium text-text-primary">FOR</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-text-tertiary">
              {forCount} {forCount === 1 ? 'vote' : 'votes'}
            </span>
            <span className="text-lg font-bold text-green-500">
              {forPercentage.toFixed(1)}%
            </span>
          </div>
        </div>
        
        <div className="h-8 bg-surface-tertiary rounded-lg overflow-hidden relative">
          <motion.div
            className="h-full bg-green-500/30 border-r-4 border-green-500"
            initial={{ width: 0 }}
            animate={{ width: `${forPercentage}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
          <div className="absolute inset-0 flex items-center px-3">
            <span className="text-xs font-medium text-text-primary">
              {forWeight.toLocaleString()} GOV
            </span>
          </div>
        </div>
      </div>

      {/* AGAINST Votes */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ThumbsDown className="w-5 h-5 text-red-500" />
            <span className="text-sm font-medium text-text-primary">AGAINST</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-text-tert