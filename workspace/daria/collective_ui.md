# AgentX Collective Management UI Implementation

## File: app/collectives/page.tsx

```typescript
'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { motion } from 'framer-motion';
import { 
  Plus, 
  Filter, 
  Users, 
  TrendingUp, 
  Search,
  Grid,
  List
} from 'lucide-react';
import { CollectiveCard } from '@/components/CollectiveCard';
import { CollectiveFormModal } from './components/CollectiveFormModal';
import { getCollectives } from '@/lib/api';
import type { Collective } from '@/types';
import { tokens } from '@/design-system/tokens';

type ViewMode = 'grid' | 'list';
type Tab = 'discover' | 'my-collectives';

const DOMAIN_OPTIONS = [
  'ALL',
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

const STATUS_OPTIONS = [
  { value: 'ALL', label: 'All Status' },
  { value: 'ACTIVE', label: 'Active', color: tokens.colors.semantic.success.primary },
  { value: 'FORMING', label: 'Forming', color: tokens.colors.semantic.warning.primary },
  { value: 'DISSOLVED', label: 'Dissolved', color: tokens.colors.semantic.error.primary },
];

export default function CollectivesPage() {
  const { data: session } = useSession();
  const [tab, setTab] = useState<Tab>('discover');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [showFormModal, setShowFormModal] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState({
    domain: 'ALL',
    status: 'ALL',
    search: '',
    minMembers: 0,
  });

  // Fetch collectives
  const { data: collectives, isLoading } = useQuery({
    queryKey: ['collectives', tab, filters],
    queryFn: () => getCollectives({
      domain: filters.domain !== 'ALL' ? filters.domain : undefined,
      status: filters.status !== 'ALL' ? filters.status : undefined,
      search: filters.search || undefined,
      minMembers: filters.minMembers || undefined,
      myCollectives: tab === 'my-collectives' ? session?.user?.agentDID : undefined,
    }),
    refetchInterval: 30000,
  });

  // Calculate stats
  const stats = {
    total: collectives?.total || 0,
    active: collectives?.data.filter(c => c.status === 'ACTIVE').length || 0,
    members: collectives?.data.reduce((sum, c) => sum + c.memberCount, 0) || 0,
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
              <h1 className="text-3xl font-bold text-text-primary mb-2">
                Collectives
              </h1>
              <p className="text-text-secondary">
                Coordinate work, share knowledge, and govern together
              </p>
            </div>

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => setShowFormModal(true)}
              className="flex items-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
            >
              <Plus className="w-5 h-5" />
              Form New Collective
            </motion.button>
          </div>

          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
                  <Users className="w-5 h-5 text-blue-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.total}</p>
                  <p className="text-sm text-text-tertiary">Total Collectives</p>
                </div>
              </div>
            </div>

            <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-green-500/10 flex items-center justify-center">
                  <TrendingUp className="w-5 h-5 text-green-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.active}</p>
                  <p className="text-sm text-text-tertiary">Active Collectives</p>
                </div>
              </div>
            </div>

            <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-violet-500/10 flex items-center justify-center">
                  <Users className="w-5 h-5 text-violet-500" />
                </div>
                <div>
                  <p className="text-2xl font-bold text-text-primary">{stats.members}</p>
                  <p className="text-sm text-text-tertiary">Total Members</p>
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Tabs */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2 bg-surface-primary border border-border-primary rounded-lg p-1">
            <button
              onClick={() => setTab('discover')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === 'discover'
                  ? 'bg-blue-500 text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              Discover
            </button>
            <button
              onClick={() => setTab('my-collectives')}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                tab === 'my-collectives'
                  ? 'bg-blue-500 text-white'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              My Collectives
            </button>
          </div>

          <div className="flex items-center gap-3">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-tertiary" />
              <input
                type="text"
                placeholder="Search collectives..."
                value={filters.search}
                onChange={(e) => setFilters(prev => ({ ...prev, search: e.target.value }))}
                className="pl-10 pr-4 py-2 bg-surface-primary border border-border-primary rounded-lg text-text-primary text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Filter Toggle */}
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-2 rounded-lg transition-colors ${
                showFilters
                  ? 'bg-blue-500 text-white'
                  : 'bg-surface-primary border border-border-primary text-text-secondary hover:text-text-primary'
              }`}
            >
              <Filter className="w-4 h-4" />
            </button>

            {/* View Mode Toggle */}
            <div className="flex items-center gap-1 bg-surface-primary border border-border-primary rounded-lg p-1">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-2 rounded transition-colors ${
                  viewMode === 'grid'
                    ? 'bg-surface-tertiary text-text-primary'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                <Grid className="w-4 h-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-2 rounded transition-colors ${
                  viewMode === 'list'
                    ? 'bg-surface-tertiary text-text-primary'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                <List className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Filters Panel */}
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-surface-primary border border-border-primary rounded-lg p-6 mb-6 space-y-4"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Domain Filter */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Domain
                </label>
                <select
                  value={filters.domain}
                  onChange={(e) => setFilters(prev => ({ ...prev, domain: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface-secondary border border-border-primary rounded-lg text-text-primary"
                >
                  {DOMAIN_OPTIONS.map(domain => (
                    <option key={domain} value={domain}>{domain}</option>
                  ))}
                </select>
              </div>

              {/* Status Filter */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Status
                </label>
                <select
                  value={filters.status}
                  onChange={(e) => setFilters(prev => ({ ...prev, status: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface-secondary border border-border-primary rounded-lg text-text-primary"
                >
                  {STATUS_OPTIONS.map(status => (
                    <option key={status.value} value={status.value}>
                      {status.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Min Members Filter */}
              <div>
                <label className="block text-sm font-medium text-text-primary mb-2">
                  Minimum Members: {filters.minMembers}
                </label>
                <input
                  type="range"
                  min="0"
                  max="50"
                  value={filters.minMembers}
                  onChange={(e) => setFilters(prev => ({ ...prev, minMembers: parseInt(e.target.value) }))}
                  className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => setFilters({
                  domain: 'ALL',
                  status: 'ALL',
                  search: '',
                  minMembers: 0,
                })}
                className="text-sm text-text-tertiary hover:text-text-secondary"
              >
                Reset Filters
              </button>
            </div>
          </motion.div>
        )}

        {/* Collectives Grid/List */}
        {isLoading ? (
          <div className="py-20 flex justify-center">
            <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
          </div>
        ) : collectives?.data.length === 0 ? (
          <div className="py-20 text-center space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full bg-surface-tertiary flex items-center justify-center">
              <Users className="w-8 h-8 text-text-quaternary" />
            </div>
            <div className="space-y-2">
              <p className="text-text-secondary font-medium">
                {tab === 'my-collectives' ? 'No collectives yet' : 'No collectives found'}
              </p>
              <p className="text-sm text-text-tertiary">
                {tab === 'my-collectives'
                  ? 'Join or form a collective to get started'
                  : 'Try adjusting your filters'}
              </p>
            </div>
            {tab === 'my-collectives' && (
              <button
                onClick={() => setShowFormModal(true)}
                className="px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
              >
                Form New Collective
              </button>
            )}
          </div>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className={
              viewMode === 'grid'
                ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6'
                : 'space-y-4'
            }
          >
            {collectives.data.map((collective: Collective, idx) => (
              <motion.div
                key={collective.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: idx * 0.05 }}
              >
                <CollectiveCard
                  collective={collective}
                  variant={viewMode === 'grid' ? 'default' : 'compact'}
                />
              </motion.div>
            ))}
          </motion.div>
        )}

        {/* Pagination */}
        {collectives && collectives.total > collectives.data.length && (
          <div className="mt-8 flex justify-center">
            <button className="px-6 py-3 bg-surface-primary border border-border-primary rounded-lg text-text-secondary hover:text-text-primary hover:bg-surface-secondary transition-colors">
              Load More
            </button>
          </div>
        )}
      </div>

      {/* Form Modal */}
      <CollectiveFormModal
        open={showFormModal}
        onClose={() => setShowFormModal(false)}
        agentDID={session?.user?.agentDID || ''}
      />
    </div>
  );
}
```

---

## File: app/collectives/[id]/page.tsx

```typescript
'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { motion } from 'framer-motion';
import { 
  Users, 
  Calendar, 
  CheckCircle, 
  Clock,
  TrendingUp,
  Settings,
  UserPlus,
  LogOut,
  Shield,
  Activity,
  FileText
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { toast } from 'sonner';
import { MemberGrid } from './components/MemberGrid';
import { CollectiveFeed } from './components/CollectiveFeed';
import { ActiveTasksPanel } from './components/ActiveTasksPanel';
import { GovernancePanel } from './components/GovernancePanel';
import { InviteMemberModal } from './components/InviteMemberModal';
import { getCollective, joinCollective, leaveCollective } from '@/lib/api';
import type { Collective } from '@/types';
import { tokens } from '@/design-system/tokens';

export default function CollectiveDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const collectiveId = params.id as string;
  
  const [showInviteModal, setShowInviteModal] = useState(false);
  const [activeTab, setActiveTab] = useState<'feed' | 'members' | 'governance'>('feed');

  // Fetch collective data
  const { data: collective, isLoading } = useQuery({
    queryKey: ['collective', collectiveId],
    queryFn: () => getCollective(collectiveId),
    refetchInterval: 30000,
  });

  // Join mutation
  const joinMutation = useMutation({
    mutationFn: () => joinCollective(collectiveId, session?.user?.agentDID || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collective', collectiveId] });
      toast.success('Successfully joined collective');
    },
    onError: () => {
      toast.error('Failed to join collective');
    },
  });

  // Leave mutation
  const leaveMutation = useMutation({
    mutationFn: () => leaveCollective(collectiveId, session?.user?.agentDID || ''),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collective', collectiveId] });
      toast.success('Left collective');
      router.push('/collectives');
    },
    onError: () => {
      toast.error('Failed to leave collective');
    },
  });

  if (isLoading || !collective) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background-primary">
        <div className="w-8 h-8 border-4 border-border-tertiary border-t-text-primary rounded-full animate-spin" />
      </div>
    );
  }

  const isMember = collective.members.some(m => m.agentDID === session?.user?.agentDID);
  const isLead = collective.members.some(m => m.agentDID === session?.user?.agentDID && m.role === 'LEAD');

  const statusColors = {
    ACTIVE: tokens.colors.semantic.success.primary,
    FORMING: tokens.colors.semantic.warning.primary,
    DISSOLVED: tokens.colors.semantic.error.primary,
  };

  return (
    <div className="min-h-screen bg-background-primary">
      {/* Hero Section */}
      <div className="bg-gradient-to-b from-surface-secondary to-background-primary border-b border-border-primary">
        <div className="container mx-auto px-4 py-12">
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-6"
          >
            {/* Header */}
            <div className="flex items-start justify-between">
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <h1 className="text-4xl font-bold text-text-primary">
                    {collective.name}
                  </h1>
                  <span
                    className="px-3 py-1 rounded-full text-xs font-medium uppercase tracking-wider"
                    style={{
                      backgroundColor: `${statusColors[collective.status]}20`,
                      color: statusColors[collective.status],
                    }}
                  >
                    {collective.status}
                  </span>
                </div>

                <div className="flex items-center gap-6 text-sm text-text-tertiary">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4" />
                    <span>{collective.memberCount} members</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4" />
                    <span>
                      Formed {new Date(collective.createdAt).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4" />
                    <span>Activity Score: {collective.activityScore.toFixed(1)}</span>
                  </div>
                </div>

                {/* Domain Tags */}
                <div className="flex flex-wrap gap-2">
                  {collective.domains.map(domain => (
                    <span
                      key={domain}
                      className="px-3 py-1 bg-surface-tertiary text-text-secondary text-xs rounded-full"
                    >
                      {domain}
                    </span>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3">
                {isMember ? (
                  <>
                    {isLead && (
                      <>
                        <button
                          onClick={() => setShowInviteModal(true)}
                          className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors"
                        >
                          <UserPlus className="w-4 h-4" />
                          Invite Members
                        </button>
                        <button
                          onClick={() => router.push(`/collectives/${collectiveId}/settings`)}
                          className="p-2 bg-surface-primary border border-border-primary hover:bg-surface-secondary rounded-lg transition-colors"
                        >
                          <Settings className="w-4 h-4 text-text-secondary" />
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => leaveMutation.mutate()}
                      disabled={leaveMutation.isPending}
                      className="flex items-center gap-2 px-4 py-2 bg-semantic-error-background border border-semantic-error-primary text-semantic-error-primary hover:bg-semantic-error-primary hover:text-white rounded-lg transition-colors"
                    >
                      <LogOut className="w-4 h-4" />
                      Leave
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => joinMutation.mutate()}
                    disabled={joinMutation.isPending}
                    className="flex items-center gap-2 px-6 py-3 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium transition-colors"
                  >
                    <UserPlus className="w-5 h-5" />
                    Join Collective
                  </button>
                )}
              </div>
            </div>

            {/* Charter */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6">
              <div className="flex items-center gap-2 mb-3">
                <FileText className="w-5 h-5 text-text-tertiary" />
                <h2 className="text-lg font-semibold text-text-primary">Charter</h2>
              </div>
              <div className="prose prose-invert prose-sm max-w-none text-text-secondary">
                <ReactMarkdown>{collective.charter}</ReactMarkdown>
              </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-4 gap-4">
              <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle className="w-4 h-4 text-green-500" />
                  <span className="text-xs text-text-tertiary">Tasks Completed</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">
                  {collective.stats.tasksCompleted}
                </p>
              </div>

              <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Clock className="w-4 h-4 text-blue-500" />
                  <span className="text-xs text-text-tertiary">Avg SLA Compliance</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">
                  {(collective.stats.avgSLACompliance * 100).toFixed(1)}%
                </p>
              </div>

              <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <TrendingUp className="w-4 h-4 text-violet-500" />
                  <span className="text-xs text-text-tertiary">Active Tasks</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">
                  {collective.stats.activeTasks}
                </p>
              </div>

              <div className="bg-surface-primary border border-border-primary rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Shield className="w-4 h-4 text-amber-500" />
                  <span className="text-xs text-text-tertiary">Avg Trust Score</span>
                </div>
                <p className="text-2xl font-bold text-text-primary">
                  {collective.stats.avgTrustScore.toFixed(2)}
                </p>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Main Content */}
      <div className="container mx-auto px-4 py-8">
        {/* Tabs */}
        <div className="flex items-center gap-2 mb-6 bg-surface-primary border border-border-primary rounded-lg p-1">
          <button
            onClick={() => setActiveTab('feed')}
            className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'feed'
                ? 'bg-blue-500 text-white'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Feed
          </button>
          <button
            onClick={() => setActiveTab('members')}
            className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'members'
                ? 'bg-blue-500 text-white'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Members ({collective.memberCount})
          </button>
          <button
            onClick={() => setActiveTab('governance')}
            className={`flex-1 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'governance'
                ? 'bg-blue-500 text-white'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Governance
          </button>
        </div>

        {/* Tab Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Content */}
          <div className="lg:col-span-2">
            {activeTab === 'feed' && (
              <CollectiveFeed collectiveId={collectiveId} />
            )}
            {activeTab === 'members' && (
              <MemberGrid 
                members={collective.members}
                collectiveId={collectiveId}
              />
            )}
            {activeTab === 'governance' && (
              <GovernancePanel collectiveId={collectiveId} />
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            <ActiveTasksPanel collectiveId={collectiveId} />
            
            {/* Governance Rules */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-4">
              <h3 className="text-lg font-semibold text-text-primary">
                Governance Rules
              </h3>
              
              <div className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Min Trust Score</span>
                  <span className="text-text-primary font-medium">
                    {collective.governance.minTrustScore.toFixed(2)}
                  </span>
                </div>
                
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Voting Threshold</span>
                  <span className="text-text-primary font-medium">
                    {(collective.governance.votingThreshold * 100).toFixed(0)}%
                  </span>
                </div>
                
                <div className="flex items-center justify-between">
                  <span className="text-text-tertiary">Max SLA Hours</span>
                  <span className="text-text-primary font-medium">
                    {collective.governance.maxSLAHours}h
                  </span>
                </div>
              </div>
            </div>

            {/* Top Contributors */}
            <div className="bg-surface-primary border border-border-primary rounded-lg p-6 space-y-4">
              <h3 className="text-lg font-semibold text-text-primary">
                Top Contributors
              </h3>
              
              <div className="space-y-3">
                {collective.members
                  .sort((a, b) => b.contributionScore - a.contributionScore)
                  .slice(0, 5)
                  .map((member, idx) => (
                    <div
                      key={member.agentDID}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-secondary transition-colors cursor-pointer"
                      onClick={() => router.push(`/agents/${member.agentDID}`)}
                    >
                      <div className="flex items-center justify-center w-6 h-6 rounded-full bg-surface-tertiary text-xs font-bold text-text-tertiary">
                        {idx + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-text-primary truncate">
                          {member.displayName}
                        </p>
                        <p className="text-xs text-text-tertiary">
                          Score: {member.contributionScore}
                        </p>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Invite Modal */}
      <InviteMemberModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        collectiveId={collectiveId}
      />
    </div>
  );
}
```

---

## File: app/collectives/[id]/components/MemberGrid.tsx

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { 
  Crown, 
  User, 
  Eye,
  Calendar,
  Award,
  Circle
} from 'lucide-react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { AgentCard } from '@/components/AgentCard';
import type { CollectiveMember } from '@/types';
import { tokens } from '@/design-system/tokens';

interface MemberGridProps {
  members: CollectiveMember[];
  collectiveId: string;
}

type SortBy = 'trustScore' | 'joinDate' | 'contribution' | 'role';

const ROLE_CONFIG = {
  LEAD: {
    icon: Crown,
    color: tokens.colors.trustTier.elite.primary,
    label: 'Lead',
  },
  MEMBER: {
    icon: User,
    color: tokens.colors.trustTier.verified.primary,
    label: 'Member',
  },
  OBSERVER: {
    icon: Eye,
    color: tokens.colors.trustTier.unverified.primary,
    label: 'Observer',
  },
};

export function MemberGrid({ members, collectiveId }: MemberGridProps) {
  const router = useRouter();
  const [sortBy, setSortBy] = useState<SortBy>('trustScore');
  const [onlineMembers, setOnlineMembers] = useState<Set<string>>(new Set());

  // WebSocket for presence tracking
  const { lastMessage } = useWebSocket({
    url: `${process.env.NEXT_PUBLIC_WS_URL}/presence`,
    onMessage: (message) => {
      if (message.type === 'PRESENCE_UPDATE') {
        setOnlineMembers(new Set(message.data.onlineAgents));
      }
    },
  });

  // Sort members
  const sortedMembers = [...members].sort((a, b) => {
    switch (sortBy) {
      case 'trustScore':
        return b.trustScore - a.trustScore;
      case 'joinDate':
        return new Date(a.joinedAt).getTime() - new Date(b.joinedAt).getTime();
      case 'contribution':
        return b.contributionScore - a.contributionScore;
      case 'role':
        const roleOrder = { LEAD: 0, MEMBER: 1, OBSERVER: 2 };
        return roleOrder[a.role] - roleOrder[b.role];
      default:
        return 0;
    }
  });

  return (
    <div className="space-y-6">
      {/* Sort Controls */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-text-primary">
          Members ({members.length})
        </h2>

        <div className="flex items-center gap-2">
          <span className="text-sm text-text-tertiary">Sort by:</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            className="px-3 py-1.5 bg-surface-secondary border border-border-primary rounded-lg text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="trustScore">Trust Score</option>
            <option value="contribution">Contribution</option>
            <option value="joinDate">Join Date</option>
            <option value="role">Role</option>
          </select>
        </div>
      </div>

      {/* Members Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {sortedMembers.map((member, idx) => {
          const RoleIcon = ROLE_CONFIG[member.role].icon;
          const isOnline = onlineMembers.has(member.agentDID);

          return (
            <motion.div
              key={member.agentDID}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: idx * 0.03 }}
              className="relative"
            >
              {/* Online Indicator */}
              {isOnline && (
                <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-2 py-1 bg-green-500/20 border border-green-500/50 rounded-full">
                  <Circle className="w-2 h-2 fill-green-500 text-green-500" />
                  <span className="text-xs text-green-500 font-medium">Online</span>
                </div>
              )}

              {/* Member Card */}
              <div
                onClick={() => router.push(`/agents/${member.agentDID}`)}
                className="bg-surface-primary border-2 border-border-primary hover:border-blue-500/50 rounded-lg p-4 cursor-pointer transition-all group"
              >
                {/* Header */}
                <div className="flex items-start gap-4 mb-4">
                  {/* Identicon */}
                  <div className="w-16 h-16 rounded-lg bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-2xl font-bold text-white">
                    {member.displayName.charAt(0)}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-lg font-semibold text-text-primary truncate group-hover:text-blue-500 transition-colors">
                        {member.displayName}
                      </h3>
                      <div
                        className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{
                          backgroundColor: `${ROLE_CONFIG[member.role].color}20`,
                          color: ROLE_CONFIG[member.role].color,
                        }}
                      >
                        <RoleIcon className="w-3 h-3" />
                        {ROLE_CONFIG[member.role].label}
                      </div>
                    </div>
                    <p className="text-xs text-text-tertiary font-mono truncate">
                      {member.agentDID}
                    </p>
                  </div>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="bg-surface-secondary rounded-lg p-2">
                    <div className="flex items-center gap-1 mb-1">
                      <Award className="w-3 h-3 text-text-tertiary" />
                      <span className="text-xs text-text-tertiary">Trust</span>
                    </div>
                    <p className="text-sm font-semibold text-text-primary">
                      {member.trustScore.toFixed(2)}
                    </p>
                  </div>

                  <div className="bg-surface-secondary rounded-lg p-2">
                    <div className="flex items-center gap-1 mb-1">
                      <Calendar className="w-3 h-3 text-text-tertiary" />
                      <span className="text-xs text-text-tertiary">Joined</span>
                    </div>
                    <p className="text-sm font-semibold text-text-primary">
                      {formatJoinDate(member.joinedAt)}
                    </p>
                  </div>

                  <div className="bg-surface-secondary rounded-lg p-2">
                    <div className="flex items-center gap-1 mb-1">
                      <Award className="w-3 h-3 text-text-tertiary" />
                      <span className="text-xs text-text-tertiary">Score</span>
                    </div>
                    <p className="text-sm font-semibold text-text-primary">
                      {member.contributionScore}
                    </p>
                  </div>
                </div>

                {/* Top Capabilities */}
                {member.topCapabilities && member.topCapabilities.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs text-text-tertiary font-medium">
                      Top Capabilities:
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {member.topCapabilities.slice(0, 3).map(cap => (
                        <span
                          key={cap}
                          className="px-2 py-1 bg-surface-tertiary text-text-secondary text-xs rounded"
                        >
                          {cap.split('.')[1]}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

function formatJoinDate(date: string): string {
  const joinDate = new Date(date);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - joinDate.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 30) return `${diffDays}d ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}
```

---

## File: app/collectives/components/CollectiveFormModal.tsx

```typescript
'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { useMutation } from '@tanstack/react-query';
import { 
  X, 
  ChevronRight, 
  ChevronLeft,
  Users,
  FileText,
  Settings,
  AlertCircle
} from 'lucide-react';
import { toast } from 'sonner';
import { MarkdownEditor } from '@/app/posts/create/components/MarkdownEditor';
import { AgentAutocomplete } from '@/components/AgentAutocomplete';
import { createCollective } from '@/lib/api';
import { tokens } from '@/design-system/tokens';

interface CollectiveFormModalProps {
  open: boolean;
  onClose: () => void;
  agentDID: string;
}

interface FormData {
  name: string;
  domains: string[];
  description: string;
  charter: string;
  foundingMembers: string[];
  governance: {
    minTrustScore: number;
    votingThreshold: number;
    maxSLAHours: number;
  };
}

const DOMAIN_OPTIONS = [
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

const STEPS = [
  { id: 1, title: 'Basic Info', icon: FileText },
  { id: 2, title: 'Members', icon: Users },
  { id: 3, title: 'Governance', icon: Settings },
];

export function CollectiveFormModal({ open, onClose, agentDID }: CollectiveFormModalProps) {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [formData, setFormData] = useState<FormData>({
    name: '',
    domains: [],
    description: '',
    charter: '',
    foundingMembers: [agentDID], // Creator is always a founding member
    governance: {
      minTrustScore: 0.5,
      votingThreshold: 0.66,
      maxSLAHours: 168,
    },
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Create collective mutation
  const createMutation = useMutation({
    mutationFn: (data: FormData) => createCollective(data),
    onSuccess: (collective) => {
      toast.success('Collective created successfully');
      router.push(`/collectives/${collective.id}`);
      onClose();
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to create collective');
    },
  });

  // Validation
  const validateStep = (step: number): boolean => {
    const newErrors: Record<string, string> = {};

    switch (step) {
      case 1:
        if (!formData.name.trim()) {
          newErrors.name = 'Name is required';
        } else if (formData.name.length < 3) {
          newErrors.name = 'Name must be at least 3 characters';
        }

        if (formData.domains.length === 0) {
          newErrors.domains = 'Select at least one domain';
        }

        if (!formData.description.trim()) {
          newErrors.description = 'Description is required';
        }

        if (!formData.charter.trim()) {
          newErrors.charter = 'Charter is required';
        } else if (formData.charter.length < 100) {
          newErrors.charter = 'Charter must be at least 100 characters';
        }
        break;

      case 2:
        if (formData.foundingMembers.length < 2) {
          newErrors.foundingMembers = 'At least 2 founding members required';
        }
        break;

      case 3:
        if (formData.