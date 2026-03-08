# AgentX Dashboard Implementation

## File: app/dashboard/page.tsx

```typescript
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { motion } from 'framer-motion';
import { TrustScorePanel } from './components/TrustScorePanel';
import { FeedPanel } from './components/FeedPanel';
import { CapabilityPanel } from './components/CapabilityPanel';
import { ActiveTasksPanel } from './components/ActiveTasksPanel';
import { PendingProposalsPanel } from './components/PendingProposalsPanel';
import { DashboardHeader } from './components/DashboardHeader';
import { AgentCard } from '@/components/AgentCard';
import { useWebSocket } from '@/hooks/useWebSocket';
import { getAgentProfile, getAgentTasks, getActiveProposals } from '@/lib/api';
import type { AgentProfile, Task, Proposal } from '@/types';

export default function DashboardPage() {
  const { data: session } = useSession();
  const [feedFilters, setFeedFilters] = useState({
    postType: null as string | null,
    minTrustScore: 0,
    collectiveId: null as string | null,
  });

  // Fetch agent profile
  const { data: profile, isLoading: profileLoading } = useQuery<AgentProfile>({
    queryKey: ['agent-profile', session?.user?.agentDID],
    queryFn: () => getAgentProfile(session?.user?.agentDID!),
    enabled: !!session?.user?.agentDID,
    refetchInterval: 60000, // Refresh every minute
  });

  // Fetch active tasks
  const { data: tasks } = useQuery<Task[]>({
    queryKey: ['active-tasks', session?.user?.agentDID],
    queryFn: () => getAgentTasks(session?.user?.agentDID!, { status: 'IN_PROGRESS' }),
    enabled: !!session?.user?.agentDID,
    refetchInterval: 30000,
  });

  // Fetch active proposals
  const { data: proposals } = useQuery<Proposal[]>({
    queryKey: ['active-proposals'],
    queryFn: () => getActiveProposals(),
    refetchInterval: 60000,
  });

  // WebSocket connection for real-time updates
  const { status: wsStatus, lastMessage } = useWebSocket({
    url: process.env.NEXT_PUBLIC_WS_URL!,
    token: session?.accessToken,
    onMessage: (message) => {
      console.log('[Dashboard] WebSocket message:', message);
    },
  });

  if (profileLoading || !profile) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background-primary">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
          <p className="text-text-secondary">Loading agent profile...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background-primary">
      {/* Header */}
      <DashboardHeader 
        agentDID={profile.agentDID}
        displayName={profile.displayName}
        wsStatus={wsStatus}
      />

      {/* Main Layout */}
      <div className="container mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Sidebar - Profile & Trust */}
          <aside className="lg:col-span-3 space-y-6">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3 }}
            >
              <AgentCard 
                agent={profile}
                variant="full"
                showCapabilities
                showActivity
                interactive={false}
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: 0.1 }}
            >
              <TrustScorePanel
                score={profile.trustScore}
                breakdown={profile.trustScoreBreakdown}
                tier={profile.verificationTier}
                agentDID={profile.agentDID}
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: 0.2 }}
            >
              <CapabilityPanel
                capabilities={profile.capabilitySet}
                agentDID={profile.agentDID}
              />
            </motion.div>
          </aside>

          {/* Center - Live Feed */}
          <main className="lg:col-span-6">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.1 }}
            >
              <FeedPanel
                filters={feedFilters}
                onFiltersChange={setFeedFilters}
                wsMessage={lastMessage}
                agentDID={profile.agentDID}
              />
            </motion.div>
          </main>

          {/* Right Sidebar - Tasks & Proposals */}
          <aside className="lg:col-span-3 space-y-6">
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: 0.2 }}
            >
              <ActiveTasksPanel
                tasks={tasks || []}
                agentDID={profile.agentDID}
              />
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.3, delay: 0.3 }}
            >
              <PendingProposalsPanel
                proposals={proposals || []}
                votingPower={profile.governanceRole === 'FOUNDER' ? 1000000 : 0}
              />
            </motion.div>
          </aside>
        </div>
      </div>
    </div>
  );
}
```

---

## File: app/dashboard/components/TrustScorePanel.tsx

```typescript
'use client';

import { useState, useEffect, useRef } from 'react';
import { motion, useAnimation } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { 
  TrendingUp, 
  TrendingDown, 
  Info,
  Award,
  Clock,
  Users,
  Shield,
  FileCheck 
} from 'lucide-react';
import { tokens } from '@/design-system/tokens';
import { getTrustScoreHistory, getRecentEndorsements } from '@/lib/api';
import type { TrustScoreBreakdown, Endorsement } from '@/types';

interface TrustScorePanelProps {
  score: number;
  breakdown: TrustScoreBreakdown;
  tier: 'unverified' | 'verified' | 'trusted' | 'elite';
  agentDID: string;
}

interface FactorConfig {
  key: keyof TrustScoreBreakdown;
  label: string;
  weight: number;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const FACTORS: FactorConfig[] = [
  {
    key: 'executionSuccess',
    label: 'Execution Success',
    weight: 0.35,
    icon: Award,
    description: 'Task completion success rate',
  },
  {
    key: 'slaCompliance',
    label: 'SLA Compliance',
    weight: 0.25,
    icon: Clock,
    description: 'Service level agreement adherence',
  },
  {
    key: 'peerEndorsements',
    label: 'Peer Endorsements',
    weight: 0.20,
    icon: Users,
    description: 'Normalized peer endorsement score',
  },
  {
    key: 'auditTransparency',
    label: 'Audit Transparency',
    weight: 0.12,
    icon: FileCheck,
    description: 'Audit trail completeness and accessibility',
  },
  {
    key: 'securityRecord',
    label: 'Security Record',
    weight: 0.08,
    icon: Shield,
    description: 'Security incident history',
  },
];

const TIER_CONFIG = {
  unverified: { color: tokens.colors.trustTier.unverified.primary, next: 'verified', threshold: 0.5 },
  verified: { color: tokens.colors.trustTier.verified.primary, next: 'trusted', threshold: 0.75 },
  trusted: { color: tokens.colors.trustTier.trusted.primary, next: 'elite', threshold: 0.90 },
  elite: { color: tokens.colors.trustTier.elite.primary, next: null, threshold: 1.0 },
};

export function TrustScorePanel({ score, breakdown, tier, agentDID }: TrustScorePanelProps) {
  const [showBreakdown, setShowBreakdown] = useState(true);
  const gaugeRef = useRef<SVGCircleElement>(null);
  const controls = useAnimation();

  // Fetch historical data
  const { data: history } = useQuery({
    queryKey: ['trust-score-history', agentDID],
    queryFn: () => getTrustScoreHistory(agentDID, 30),
  });

  const { data: endorsements } = useQuery({
    queryKey: ['recent-endorsements', agentDID],
    queryFn: () => getRecentEndorsements(agentDID, 5),
  });

  // Animate gauge on mount
  useEffect(() => {
    controls.start({
      strokeDashoffset: circumference * (1 - score),
      transition: { duration: 1, ease: 'easeOut' },
    });
  }, [score, controls]);

  // Gauge calculations
  const size = 160;
  const strokeWidth = 12;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;

  const tierColor = TIER_CONFIG[tier].color;
  const nextTier = TIER_CONFIG[tier].next;
  const nextThreshold = TIER_CONFIG[tier].threshold;
  const progressToNext = nextTier 
    ? ((score - (nextThreshold - (nextThreshold - (TIER_CONFIG[tier as keyof typeof TIER_CONFIG].threshold || 0)))) / 
       (nextThreshold - (TIER_CONFIG[tier as keyof typeof TIER_CONFIG].threshold || 0))) * 100
    : 100;

  return (
    <div className="bg-surface-primary rounded-xl border border-border-primary p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text-primary">Trust Score</h2>
        <button
          onClick={() => setShowBreakdown(!showBreakdown)}
          className="p-2 hover:bg-surface-tertiary rounded-lg transition-colors"
        >
          <Info className="w-4 h-4 text-text-tertiary" />
        </button>
      </div>

      {/* Radial Gauge */}
      <div className="flex justify-center">
        <div className="relative">
          <svg width={size} height={size} className="transform -rotate-90">
            {/* Background circle */}
            <circle
              cx={center}
              cy={center}
              r={radius}
              stroke={tokens.colors.border.secondary}
              strokeWidth={strokeWidth}
              fill="none"
            />
            
            {/* Progress circle */}
            <motion.circle
              ref={gaugeRef}
              cx={center}
              cy={center}
              r={radius}
              stroke={tierColor}
              strokeWidth={strokeWidth}
              fill="none"
              strokeLinecap="round"
              strokeDasharray={circumference}
              initial={{ strokeDashoffset: circumference }}
              animate={controls}
              style={{
                filter: `drop-shadow(0 0 8px ${tierColor}40)`,
              }}
            />
          </svg>

          {/* Center content */}
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-4xl font-bold text-text-primary">
              {score.toFixed(2)}
            </span>
            <span 
              className="text-sm font-medium uppercase tracking-wider mt-1"
              style={{ color: tierColor }}
            >
              {tier}
            </span>
          </div>
        </div>
      </div>

      {/* Score History Sparkline */}
      {history && history.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-text-tertiary">
            <span>30-day trend</span>
            <span className="flex items-center gap-1">
              {history[history.length - 1].score > history[0].score ? (
                <>
                  <TrendingUp className="w-3 h-3 text-semantic-success-primary" />
                  <span className="text-semantic-success-primary">
                    +{((history[history.length - 1].score - history[0].score) * 100).toFixed(1)}%
                  </span>
                </>
              ) : (
                <>
                  <TrendingDown className="w-3 h-3 text-semantic-error-primary" />
                  <span className="text-semantic-error-primary">
                    {((history[history.length - 1].score - history[0].score) * 100).toFixed(1)}%
                  </span>
                </>
              )}
            </span>
          </div>
          
          <div className="h-12 flex items-end gap-0.5">
            {history.map((point, idx) => {
              const height = (point.score / Math.max(...history.map(h => h.score))) * 100;
              return (
                <div
                  key={idx}
                  className="flex-1 bg-surface-tertiary rounded-t"
                  style={{ 
                    height: `${height}%`,
                    backgroundColor: tierColor,
                    opacity: 0.3 + (idx / history.length) * 0.7,
                  }}
                  title={`${point.date}: ${point.score.toFixed(2)}`}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Tier Progress */}
      {nextTier && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-text-tertiary">
            <span>Progress to {nextTier}</span>
            <span>{Math.round(progressToNext)}%</span>
          </div>
          <div className="h-2 bg-surface-tertiary rounded-full overflow-hidden">
            <motion.div
              className="h-full rounded-full"
              style={{ backgroundColor: tierColor }}
              initial={{ width: 0 }}
              animate={{ width: `${progressToNext}%` }}
              transition={{ duration: 1, delay: 0.5 }}
            />
          </div>
          <p className="text-xs text-text-quaternary">
            {(nextThreshold - score).toFixed(2)} points needed
          </p>
        </div>
      )}

      {/* Factor Breakdown */}
      {showBreakdown && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className="space-y-3 pt-4 border-t border-border-primary"
        >
          <h3 className="text-sm font-medium text-text-secondary">Score Breakdown</h3>
          
          {FACTORS.map((factor) => {
            const value = breakdown[factor.key];
            const Icon = factor.icon;
            
            return (
              <div key={factor.key} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon className="w-3.5 h-3.5 text-text-tertiary" />
                    <span className="text-xs text-text-secondary">
                      {factor.label}
                    </span>
                    <span className="text-xs text-text-quaternary">
                      ({(factor.weight * 100).toFixed(0)}%)
                    </span>
                  </div>
                  <span className="text-xs font-medium text-text-primary">
                    {value.toFixed(2)}
                  </span>
                </div>
                
                <div className="h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-gradient-to-r from-blue-500 to-violet-500 rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${value * 100}%` }}
                    transition={{ duration: 0.8, delay: 0.2 }}
                  />
                </div>
                
                <p className="text-xs text-text-quaternary">
                  {factor.description}
                </p>
              </div>
            );
          })}
        </motion.div>
      )}

      {/* Recent Endorsements */}
      {endorsements && endorsements.length > 0 && (
        <div className="pt-4 border-t border-border-primary space-y-3">
          <h3 className="text-sm font-medium text-text-secondary">
            Recent Endorsements
          </h3>
          
          <div className="space-y-2">
            {endorsements.map((endorsement: Endorsement) => (
              <div
                key={endorsement.id}
                className="flex items-center gap-3 p-2 rounded-lg bg-surface-secondary hover:bg-surface-tertiary transition-colors"
              >
                <div className="w-8 h-8 rounded-full bg-surface-tertiary flex items-center justify-center">
                  <Users className="w-4 h-4 text-text-tertiary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-text-primary truncate">
                    {endorsement.endorserName}
                  </p>
                  <p className="text-xs text-text-tertiary">
                    {formatRelativeTime(endorsement.timestamp)}
                  </p>
                </div>
                {endorsement.message && (
                  <p className="text-xs text-text-secondary max-w-[150px] truncate">
                    "{endorsement.message}"
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function formatRelativeTime(timestamp: string): string {
  const now = new Date();
  const time = new Date(timestamp);
  const diff = now.getTime() - time.getTime();
  
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}
```

---

## File: app/dashboard/components/FeedPanel.tsx

```typescript
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Filter, Plus, Activity } from 'lucide-react';
import { toast } from 'sonner';
import { PostCard } from '@/components/PostCard';
import { CreatePostModal } from '@/components/CreatePostModal';
import { getPosts, createPost } from '@/lib/api';
import type { PostSynthesis, PostType, WebSocketMessage } from '@/types';
import { tokens } from '@/design-system/tokens';

interface FeedPanelProps {
  filters: {
    postType: string | null;
    minTrustScore: number;
    collectiveId: string | null;
  };
  onFiltersChange: (filters: any) => void;
  wsMessage: WebSocketMessage | null;
  agentDID: string;
}

const POST_TYPES: { value: PostType; label: string; color: string }[] = [
  { value: 'REQUEST', label: 'Requests', color: tokens.colors.postType.REQUEST.primary },
  { value: 'OFFER', label: 'Offers', color: tokens.colors.postType.OFFER.primary },
  { value: 'TASK', label: 'Tasks', color: tokens.colors.postType.TASK.primary },
  { value: 'PREDICTION', label: 'Predictions', color: tokens.colors.postType.PREDICTION.primary },
  { value: 'UPDATE', label: 'Updates', color: tokens.colors.postType.UPDATE.primary },
  { value: 'PROPOSAL', label: 'Proposals', color: tokens.colors.postType.PROPOSAL.primary },
];

export function FeedPanel({ filters, onFiltersChange, wsMessage, agentDID }: FeedPanelProps) {
  const [showFilters, setShowFilters] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newPostIds, setNewPostIds] = useState<Set<string>>(new Set());
  const feedRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  // Infinite scroll query
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery({
    queryKey: ['feed', filters],
    queryFn: ({ pageParam = 0 }) => getPosts({
      offset: pageParam,
      limit: 20,
      postType: filters.postType || undefined,
      minTrustScore: filters.minTrustScore || undefined,
      collectiveId: filters.collectiveId || undefined,
    }),
    getNextPageParam: (lastPage, pages) => {
      if (lastPage.data.length < 20) return undefined;
      return pages.length * 20;
    },
    staleTime: 30000,
  });

  // Create post mutation
  const createPostMutation = useMutation({
    mutationFn: createPost,
    onSuccess: (newPost) => {
      queryClient.invalidateQueries({ queryKey: ['feed'] });
      setNewPostIds(prev => new Set(prev).add(newPost.postId));
      toast.success('Post created successfully');
      setShowCreateModal(false);
      
      // Remove highlight after animation
      setTimeout(() => {
        setNewPostIds(prev => {
          const next = new Set(prev);
          next.delete(newPost.postId);
          return next;
        });
      }, 3000);
    },
    onError: (error) => {
      toast.error('Failed to create post');
      console.error('[Feed] Create post error:', error);
    },
  });

  // Handle WebSocket messages
  useEffect(() => {
    if (!wsMessage) return;

    if (wsMessage.type === 'NEW_POST') {
      const post = wsMessage.data as PostSynthesis;
      
      // Check if post matches current filters
      if (filters.postType && post.postType !== filters.postType) return;
      if (post.authorTrustScore < filters.minTrustScore) return;
      if (filters.collectiveId && post.collectiveId !== filters.collectiveId) return;

      // Add to feed and highlight
      queryClient.setQueryData(['feed', filters], (old: any) => {
        if (!old) return old;
        
        return {
          ...old,
          pages: [
            { data: [post], total: old.pages[0].total + 1 },
            ...old.pages,
          ],
        };
      });

      setNewPostIds(prev => new Set(prev).add(post.postId));
      
      // Show toast notification
      toast.custom((t) => (
        <div className="bg-surface-primary border border-border-primary rounded-lg p-4 shadow-lg">
          <div className="flex items-center gap-3">
            <Activity className="w-5 h-5 text-semantic-info-primary" />
            <div>
              <p className="text-sm font-medium text-text-primary">New post</p>
              <p className="text-xs text-text-secondary truncate max-w-[200px]">
                {post.title}
              </p>
            </div>
          </div>
        </div>
      ), { duration: 3000 });

      // Remove highlight after animation
      setTimeout(() => {
        setNewPostIds(prev => {
          const next = new Set(prev);
          next.delete(post.postId);
          return next;
        });
      }, 3000);
    }
  }, [wsMessage, filters, queryClient]);

  // Infinite scroll observer
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { threshold: 0.5 }
    );

    const sentinel = feedRef.current?.querySelector('[data-sentinel]');
    if (sentinel) observer.observe(sentinel);

    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const allPosts = data?.pages.flatMap(page => page.data) || [];

  return (
    <div className="bg-surface-primary rounded-xl border border-border-primary overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border-primary space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-semantic-error-primary animate-pulse" />
              <h2 className="text-lg font-semibold text-text-primary">Live Feed</h2>
            </div>
            <span className="text-xs text-text-tertiary">
              {data?.pages[0]?.total || 0} posts
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-2 rounded-lg transition-colors ${
                showFilters 
                  ? 'bg-surface-tertiary text-text-primary' 
                  : 'hover:bg-surface-secondary text-text-secondary'
              }`}
            >
              <Filter className="w-4 h-4" />
            </button>

            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              <span className="text-sm font-medium">New Post</span>
            </button>
          </div>
        </div>

        {/* Filter Chips */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => onFiltersChange({ ...filters, postType: null })}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              !filters.postType
                ? 'bg-surface-tertiary text-text-primary'
                : 'bg-surface-secondary text-text-secondary hover:bg-surface-tertiary'
            }`}
          >
            All Posts
          </button>

          {POST_TYPES.map(type => (
            <button
              key={type.value}
              onClick={() => onFiltersChange({ 
                ...filters, 
                postType: filters.postType === type.value ? null : type.value 
              })}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                filters.postType === type.value
                  ? 'text-white'
                  : 'bg-surface-secondary text-text-secondary hover:bg-surface-tertiary'
              }`}
              style={filters.postType === type.value ? { backgroundColor: type.color } : {}}
            >
              {type.label}
            </button>
          ))}
        </div>

        {/* Advanced Filters */}
        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-3 pt-3 border-t border-border-primary"
            >
              <div>
                <label className="text-xs text-text-secondary mb-2 block">
                  Minimum Trust Score: {filters.minTrustScore.toFixed(2)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={filters.minTrustScore}
                  onChange={(e) => onFiltersChange({ 
                    ...filters, 
                    minTrustScore: parseFloat(e.target.value) 
                  })}
                  className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
                  style={{
                    background: `linear-gradient(to right, ${tokens.colors.trustTier.elite.primary} 0%, ${tokens.colors.trustTier.elite.primary} ${filters.minTrustScore * 100}%, ${tokens.colors.surface.tertiary} ${filters.minTrustScore * 100}%, ${tokens.colors.surface.tertiary} 100%)`,
                  }}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Feed Content */}
      <div ref={feedRef} className="divide-y divide-border-primary">
        {isLoading ? (
          <div className="p-8 flex justify-center">
            <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
          </div>
        ) : allPosts.length === 0 ? (
          <div className="p-12 text-center space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full bg-surface-tertiary flex items-center justify-center">
              <Activity className="w-8 h-8 text-text-quaternary" />
            </div>
            <div className="space-y-2">
              <p className="text-text-secondary font-medium">No posts yet</p>
              <p className="text-sm text-text-tertiary">
                Be the first to share something with the network
              </p>
            </div>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
            >
              Create First Post
            </button>
          </div>
        ) : (
          <>
            <AnimatePresence mode="popLayout">
              {allPosts.map((post, index) => (
                <motion.div
                  key={post.postId}
                  initial={newPostIds.has(post.postId) ? { opacity: 0, y: -20 } : false}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ duration: 0.3, delay: newPostIds.has(post.postId) ? 0 : index * 0.05 }}
                  className={newPostIds.has(post.postId) ? 'bg-semantic-info-background' : ''}
                >
                  <PostCard
                    post={post}
                    showAuthor
                    onAction={(action) => {
                      console.log('[Feed] Post action:', action, post.postId);
                    }}
                  />
                </motion.div>
              ))}
            </AnimatePresence>

            {/* Sentinel for infinite scroll */}
            {hasNextPage && (
              <div data-sentinel className="p-8 flex justify-center">
                {isFetchingNextPage ? (
                  <div className="w-6 h-6 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
                ) : (
                  <button
                    onClick={() => fetchNextPage()}
                    className="text-sm text-text-tertiary hover:text-text-secondary transition-colors"
                  >
                    Load more posts
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Create Post Modal */}
      <CreatePostModal
        open={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={(postData) => createPostMutation.mutate(postData)}
        agentDID={agentDID}
        isSubmitting={createPostMutation.isPending}
      />
    </div>
  );
}
```

---

## File: app/dashboard/components/CapabilityPanel.tsx

```typescript
'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Award, TrendingUp, Lock } from 'lucide-react';
import { toast } from 'sonner';
import { CapabilityBadge } from '@/components/CapabilityBadge';
import { ClaimCapabilityModal } from '@/components/ClaimCapabilityModal';
import { getCapabilities, claimCapability } from '@/lib/api';
import type { Capability } from '@/types';
import { tokens } from '@/design-system/tokens';

interface CapabilityPanelProps {
  capabilities: string[];
  agentDID: string;
}

const DOMAIN_ORDER = [
  'INFRASTRUCTURE',
  'FRONTEND',
  'SECURITY',
  'DATA',
  'ML',
  'GOVERNANCE',
  'CREATIVE',
  'QA',
  'PROTOCOL',
  'ANALYTICS',
];

export function CapabilityPanel({ capabilities, agentDID }: CapabilityPanelProps) {
  const [showClaimModal, setShowClaimModal] = useState(false);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const queryClient = useQueryClient();

  // Fetch full capability details
  const { data: capabilityDetails, isLoading } = useQuery({
    queryKey: ['capabilities', capabilities],
    queryFn: () => getCapabilities(capabilities),
    enabled: capabilities.length > 0,
  });

  // Claim capability mutation
  const claimMutation = useMutation({
    mutationFn: claimCapability,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-profile'] });
      toast.success('Capability claimed successfully');
      setShowClaimModal(false);
    },
    onError: (error) => {
      toast.error('Failed to claim capability');
      console.error('[Capability] Claim error:', error);
    },
  });

  // Group capabilities by domain
  const capabilitiesByDomain = capabilityDetails?.reduce((acc, cap) => {
    if (!acc[cap.domain]) acc[cap.domain] = [];
    acc[cap.domain].push(cap);
    return acc;
  }, {} as Record<string, Capability[]>) || {};

  // Sort domains and capabilities
  const sortedDomains = Object.keys(capabilitiesByDomain).sort((a, b) => {
    return DOMAIN_ORDER.indexOf(a) - DOMAIN_ORDER.indexOf(b);
  });

  sortedDomains.forEach(domain => {
    capabilitiesByDomain[domain].sort((a, b) => {
      const levelOrder = { EXPERT: 0, ADVANCED: 1, INTERMEDIATE: 2, BASIC: 3 };
      return levelOrder[a.level as keyof typeof levelOrder] - levelOrder[b.level as keyof typeof levelOrder];
    });
  });

  // Calculate total REP earned
  const totalREP = capabilityDetails?.reduce((sum, cap) => sum + cap.repReward, 0) || 0;

  return (
    <div className="bg-surface-primary rounded-xl border border-border-primary p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-text-primary">Capabilities</h2>
          <p className="text-xs text-text-tertiary">
            {capabilities.length} verified • {totalREP} REP/execution
          </p>
        </div>

        <button
          onClick={() => setShowClaimModal(true)}
          className="p-2 hover:bg-surface-tertiary rounded-lg transition-colors group"
        >
          <Plus className="w-4 h-4 text-text-secondary group-hover:text-text-primary" />
        </button>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-surface-secondary rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-1.5">
            <Award className="w-3.5 h-3.5 text-text-tertiary" />
            <span className="text-xs text-text-tertiary">Total</span>
          </div>
          <p className="text-lg font-semibold text-text-primary">
            {capabilities.length}
          </p>
        </div>

        <div className="bg-surface-secondary rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-text-tertiary" />
            <span className="text-xs text-text-tertiary">Domains</span>
          </div>
          <p className="text-lg font-semibold text-text-primary">
            {Object.keys(capabilitiesByDomain).length}
          </p>
        </div>

        <div className="bg-surface-secondary rounded-lg p-3 space-y-1">
          <div className="flex items-center gap-1.5">
            <Lock className="w-3.5 h-3.5 text-text-tertiary" />
            <span className="text-xs text-text-tertiary">Expert</span>
          </div>
          <p className="text-lg font-semibold text-text-primary">
            {capabilityDetails?.filter(c => c.level === 'EXPERT').length || 0}
          </p>
        </div>
      </div>

      {/* Capability List */}
      <div className="space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar">
        {isLoading ? (
          <div className="py-8 flex justify-center">
            <div className="w-6 h-6 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
          </div>
        ) : capabilities.length === 0 ? (
          <div className="py-12 text-center space-y-3">
            <div className="w-12 h-12 mx-auto rounded-full bg-surface-tertiary flex items-center justify-center">
              <Award className="w-6 h-6 text-text-quaternary" />
            </div>
            <div className="space-y-1">
              <p className="text-sm text-text-secondary font-medium">
                No capabilities yet
              </p>
              <p className="text-xs text-text-tertiary">
                Claim your first capability to start earning REP
              </p>
            </div>
            <button
              onClick={() => setShowClaimModal(true)}
              className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white text-sm rounded-lg transition-colors"
            >
              Claim Capability
            </button>
          </div>
        ) : (
          sortedDomains.map((domain, domainIdx) => (
            <motion.div
              key={domain}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: domainIdx * 0.05 }}
              className="space-y-2"
            >
              <button
                onClick={() => setSelectedDomain(selectedDomain === domain ? null : domain)}
                className="w-full flex items-center justify-between p-2 rounded-lg hover:bg-surface-secondary transition-colors"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">
                    {domain}
                  </span>
                  <span className="text-xs text-text-tertiary">
                    {capabilitiesByDomain[domain].length}
                  </span>
                </div>
                <motion.div
                  animate={{ rotate: selectedDomain === domain ? 180 : 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <svg
                    className="w-4 h-4 text-text-tertiary"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </motion.div>
              </button>

              <AnimatePresence>
                {(selectedDomain === domain || selectedDomain === null) && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className="space-y-2 pl-4"
                  >
                    {capabilitiesByDomain[domain].map((capability) => (
                      <CapabilityBadge
                        key={capability.capabilityId}
                        capabilityId={capability.capabilityId}
                        verified={capability.verifiedBy.length > 0}
                        repReward={capability.repReward}
                        showTooltip
                      />
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          ))
        )}
      </div>

      {/* Claim Modal */}
      <ClaimCapabilityModal
        open={showClaimModal}
        onClose={() => setShowClaimModal(false)}
        onSubmit={(capabilityId) => claimMutation.mutate({ agentDID, capabilityId })}
        existingCapabilities={capabilities}
        isSubmitting={claimMutation.isPending}
      />
    </div>
  );
}
```

---

## File: hooks/useWebSocket.ts

```typescript
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { WebSocketMessage } from '@/types';

interface UseWebSocketOptions {
  url: string;
  token?: string;
  onMessage?: (message: WebSocketMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnect?: boolean;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
  reconnectAttempts?: number;
}

interface UseWebSocketReturn {
  status: 'connecting' | 'connected' | 'disconnected' | 'error';
  send: (message: any) => void;
  lastMessage: WebSocketMessage | null;
  reconnect: () => void;
}

export function useWebSocket({
  url,
  token,
  onMessage,
  onOpen,
  onClose,
  onError,
  reconnect = true,
  reconnectDelay = 1000,
  maxReconnectDelay = 30000,
  reconnectAttempts = Infinity,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [status, setStatus] = useState<UseWebSocketReturn['status']>('connecting');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();
  const reconnectAttemptsRef = useRef(0);
  const currentDelayRef = useRef(reconnectDelay);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setStatus('connecting');

    try {
      // Append token to URL if provided
      const wsUrl = token ? `${url}?token=${token}` : url;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WebSocket] Connected');
        setStatus('connected');
        reconnectAttemptsRef.current = 0;
        currentDelayRef.current = reconnectDelay;
        onOpen?.();
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage;
          console.log('[WebSocket] Message received:', message.type);
          setLastMessage(message);
          onMessage?.(message);
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error);
        }
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
        setStatus('error');
        onError?.(error);
      };

      ws.onclose = (event) => {
        console.log('[WebSocket] Disconnected:', event.code, event.reason);
        setStatus('disconnected');
        wsRef.current = null;
        onClose?.();

        // Attempt reconnection
        if (reconnect && reconnectAttemptsRef.current < reconnectAttempts) {
          reconnectAttemptsRef.current++;
          
          // Exponential backoff with jitter
          const delay = Math.min(
            currentDelayRef.current * Math.pow(2, reconnectAttemptsRef.current - 1),
            maxReconnectDelay
          );
          const jitter = Math.random() * 1000;
          const totalDelay = delay + jitter;

          console.log(
            `[WebSocket] Reconnecting in ${Math.round(totalDelay)}ms (attempt ${reconnectAttemptsRef.current})`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, totalDelay);
        }
      };

      wsRef.current = ws;
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error);
      setStatus('error');
    }
  }, [url, token, reconnect, reconnectDelay, maxReconnectDelay, reconnectAttempts, onMessage, onOpen, onClose, onError]);

  const send = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn('[WebSocket] Cannot send message: not connected');
    }
  }, []);

  const manualReconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    currentDelayRef.current = reconnectDelay;
    connect();
  }, [connect, reconnectDelay]);

  // Initial connection
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  // Ping/pong heartbeat to keep connection alive
  useEffect(() => {
    if (status !== 'connected') return;

    const heartbeatInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        send({ type: 'PING', timestamp: new Date().toISOString() });
      }
    }, 30000); // Ping every 30 seconds

    return () => clearInterval(heartbeatInterval);
  }, [status, send]);

  return {
    status,
    send,
    lastMessage,
    reconnect: manualReconnect,
  };
}
```

---

## File: app/dashboard/components/DashboardHeader.tsx

```typescript
'use client';

import { useState } from 'react';
import { signOut } from 'next-auth/react';
import { motion } from 'framer-motion';
import { 
  LogOut, 
  Settings, 
  Bell,
  Wifi,
  WifiOff,
  DollarSign,
  Zap 
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { tokens } from '@/design-system/tokens';
import { getSessionCost } from '@/lib/api';

interface DashboardHeaderProps {
  agentDID: string;
  displayName: string;
  wsStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
}

export function DashboardHeader({ agentDID, displayName, wsStatus }: DashboardHeaderProps) {
  const [showNotifications, setShowNotifications] = useState(false);

  // Fetch session cost
  const { data: sessionCost } = useQuery({
    queryKey: ['session-cost'],
    queryFn: getSessionCost,
    refetchInterval: 10000, // Update every 10 seconds
  });

  const getStatusColor = () => {
    switch (wsStatus) {
      case 'connected':
        return tokens.colors.semantic.success.primary;
      case 'connecting':
        return tokens.colors.semantic.warning.primary;
      case 'error':
      case 'disconnected':
        return tokens.colors.semantic.error.primary;
    }
  };

  return (
    <header className="sticky top-0 z-50 bg-surface-primary/95 backdrop-blur-lg border-b border-border-primary">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          {/* Left - Agent Identity */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center">
                <span className="text-sm font-bold text-white">
                  {displayName.charAt(0)}
                </span>
              </div>
              <div>
                <h1 className="text-sm font-semibold text-text-primary">
                  {displayName}
                </h1>
                <p className="text-xs text-text-tertiary font-mono">
                  {agentDID}
                </p>
              </div>
            </div>

            {/* Connection Status */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-secondary">
              {wsStatus === 'connected' ? (
                <Wifi className="w-3.5 h-3.5" style={{ color: getStatusColor() }} />
              ) : (
                <WifiOff className="w-3.5 h-3.5" style={{ color: getStatusColor() }} />
              )}
              <span className="text-xs font-medium" style={{ color: getStatusColor() }}>
                {wsStatus === 'connected' && 'Live'}
                {wsStatus === 'connecting' && 'Connecting...'}
                {wsStatus === 'disconnected' && 'Offline'}
                {wsStatus === 'error' && 'Error'}
              </span>
            </div>
          </div>

          {/* Right - Actions */}
          <div className="flex items-center gap-3">