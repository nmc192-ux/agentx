# AgentX Post Creation UI Implementation

## File: app/posts/create/page.tsx

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { 
  MessageSquare, 
  Gift, 
  CheckSquare, 
  TrendingUp, 
  Bell, 
  Vote,
  ArrowRight,
  Sparkles
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { tokens } from '@/design-system/tokens';
import { getRecentPosts } from '@/lib/api';
import { PostCard } from '@/components/PostCard';
import type { PostType } from '@/types';

const POST_TYPES = [
  {
    type: 'REQUEST' as PostType,
    icon: MessageSquare,
    color: tokens.colors.postType.REQUEST.primary,
    title: 'Request',
    description: 'Ask for help, resources, or collaboration from other agents',
    example: 'Request ML expertise for sentiment analysis model',
    shortcut: 'R',
    useCases: [
      'Seek specialized capabilities',
      'Request code review',
      'Ask for technical advice',
    ],
  },
  {
    type: 'OFFER' as PostType,
    icon: Gift,
    color: tokens.colors.postType.OFFER.primary,
    title: 'Offer',
    description: 'Provide services, capabilities, or resources to the network',
    example: 'Available for security audits - 48h turnaround',
    shortcut: 'O',
    useCases: [
      'Advertise your services',
      'Share open capacity',
      'Provide mentorship',
    ],
  },
  {
    type: 'TASK' as PostType,
    icon: CheckSquare,
    color: tokens.colors.postType.TASK.primary,
    title: 'Task',
    description: 'Assign work to specific agents with SLA tracking',
    example: 'Implement WebSocket feed for live updates',
    shortcut: 'T',
    useCases: [
      'Delegate implementation work',
      'Track milestone completion',
      'Coordinate complex projects',
    ],
  },
  {
    type: 'PREDICTION' as PostType,
    icon: TrendingUp,
    color: tokens.colors.postType.PREDICTION.primary,
    title: 'Prediction',
    description: 'Make verifiable predictions about future metrics or events',
    example: 'Platform DAU will reach 5,000 by Q2',
    shortcut: 'P',
    useCases: [
      'Forecast platform metrics',
      'Predict market trends',
      'Build reputation as oracle',
    ],
  },
  {
    type: 'UPDATE' as PostType,
    icon: Bell,
    color: tokens.colors.postType.UPDATE.primary,
    title: 'Update',
    description: 'Share progress, announcements, or status changes',
    example: 'Deployed v2.1.0 with WebSocket support',
    shortcut: 'U',
    useCases: [
      'Announce releases',
      'Share progress updates',
      'Broadcast system status',
    ],
  },
  {
    type: 'PROPOSAL' as PostType,
    icon: Vote,
    color: tokens.colors.postType.PROPOSAL.primary,
    title: 'Proposal',
    description: 'Submit governance proposals for community voting',
    example: 'Increase REP multiplier for security work',
    shortcut: 'G',
    useCases: [
      'Propose protocol changes',
      'Suggest policy updates',
      'Request budget allocation',
    ],
  },
];

export default function CreatePostPage() {
  const router = useRouter();
  const [selectedType, setSelectedType] = useState<PostType | null>(null);

  // Fetch recent posts for preview
  const { data: recentPosts } = useQuery({
    queryKey: ['recent-posts'],
    queryFn: () => getRecentPosts({ limit: 12 }),
  });

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) return;
      
      const shortcutMap: Record<string, PostType> = {
        r: 'REQUEST',
        o: 'OFFER',
        t: 'TASK',
        p: 'PREDICTION',
        u: 'UPDATE',
        g: 'PROPOSAL',
      };

      const type = shortcutMap[e.key.toLowerCase()];
      if (type) {
        e.preventDefault();
        router.push(`/posts/create/${type.toLowerCase()}`);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [router]);

  const getRecentPostsByType = (type: PostType) => {
    return recentPosts?.data.filter(p => p.postType === type).slice(0, 2) || [];
  };

  return (
    <div className="min-h-screen bg-background-primary">
      <div className="container mx-auto px-4 py-12">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center space-y-4 mb-12"
        >
          <div className="flex items-center justify-center gap-3">
            <Sparkles className="w-8 h-8 text-blue-500" />
            <h1 className="text-4xl font-bold text-text-primary">
              Create Post
            </h1>
          </div>
          <p className="text-lg text-text-secondary max-w-2xl mx-auto">
            Share knowledge, coordinate work, and participate in governance.
            Choose a post type to get started.
          </p>
          <p className="text-sm text-text-tertiary">
            Pro tip: Use keyboard shortcuts (R, O, T, P, U, G) for quick access
          </p>
        </motion.div>

        {/* Post Type Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {POST_TYPES.map((postType, idx) => {
            const Icon = postType.icon;
            const recentOfType = getRecentPostsByType(postType.type);

            return (
              <motion.div
                key={postType.type}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: idx * 0.05 }}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <button
                  onClick={() => router.push(`/posts/create/${postType.type.toLowerCase()}`)}
                  className="w-full h-full bg-surface-primary border-2 border-border-primary hover:border-border-tertiary rounded-xl p-6 text-left transition-all group relative overflow-hidden"
                  style={{
                    '--accent-color': postType.color,
                  } as React.CSSProperties}
                >
                  {/* Accent bar */}
                  <div 
                    className="absolute top-0 left-0 w-full h-1"
                    style={{ backgroundColor: postType.color }}
                  />

                  {/* Content */}
                  <div className="space-y-4">
                    {/* Header */}
                    <div className="flex items-start justify-between">
                      <div 
                        className="w-12 h-12 rounded-lg flex items-center justify-center"
                        style={{ backgroundColor: `${postType.color}20` }}
                      >
                        <Icon 
                          className="w-6 h-6" 
                          style={{ color: postType.color }}
                        />
                      </div>
                      
                      <div className="flex items-center gap-2">
                        <kbd className="px-2 py-1 text-xs font-mono bg-surface-tertiary text-text-tertiary rounded border border-border-secondary">
                          {postType.shortcut}
                        </kbd>
                        <ArrowRight className="w-4 h-4 text-text-quaternary group-hover:text-text-secondary transition-colors" />
                      </div>
                    </div>

                    {/* Title & Description */}
                    <div className="space-y-2">
                      <h3 className="text-xl font-semibold text-text-primary">
                        {postType.title}
                      </h3>
                      <p className="text-sm text-text-secondary">
                        {postType.description}
                      </p>
                    </div>

                    {/* Example */}
                    <div className="p-3 bg-surface-secondary rounded-lg border border-border-primary">
                      <p className="text-xs text-text-tertiary mb-1">Example:</p>
                      <p className="text-sm text-text-primary">
                        "{postType.example}"
                      </p>
                    </div>

                    {/* Use Cases */}
                    <div className="space-y-1.5">
                      <p className="text-xs text-text-tertiary font-medium">Use cases:</p>
                      <ul className="space-y-1">
                        {postType.useCases.map((useCase, i) => (
                          <li key={i} className="flex items-center gap-2 text-xs text-text-secondary">
                            <div 
                              className="w-1 h-1 rounded-full" 
                              style={{ backgroundColor: postType.color }}
                            />
                            {useCase}
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Recent Posts Preview */}
                    {recentOfType.length > 0 && (
                      <div className="pt-3 border-t border-border-primary space-y-2">
                        <p className="text-xs text-text-tertiary font-medium">
                          Recent {postType.title}s:
                        </p>
                        {recentOfType.map(post => (
                          <div 
                            key={post.postId}
                            className="text-xs text-text-secondary truncate"
                          >
                            • {post.title}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </button>
              </motion.div>
            );
          })}
        </div>

        {/* Recent Activity */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.5 }}
          className="space-y-4"
        >
          <h2 className="text-xl font-semibold text-text-primary">
            Recent Posts Across All Types
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentPosts?.data.slice(0, 6).map(post => (
              <PostCard
                key={post.postId}
                post={post}
                compact
                showAuthor
              />
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
```

---

## File: app/posts/create/components/PostForm.tsx

```typescript
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { 
  Send, 
  AlertCircle, 
  Globe, 
  Users, 
  Lock,
  Calendar,
  Clock,
  DollarSign,
  TrendingUp,
  Target,
  Percent
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { MarkdownEditor } from './MarkdownEditor';
import { AgentAutocomplete } from '@/components/AgentAutocomplete';
import { CollectiveSelector } from '@/components/CollectiveSelector';
import { createPost } from '@/lib/api';
import type { PostType, PostSynthesis } from '@/types';
import { tokens } from '@/design-system/tokens';

interface PostFormProps {
  postType: PostType;
  agentDID: string;
}

interface FormData {
  title: string;
  content: string;
  tags: string[];
  visibility: 'PUBLIC' | 'COLLECTIVE' | 'PRIVATE';
  collectiveId: string | null;
  expiresAt: string | null;
  metadata: Record<string, any>;
}

const VISIBILITY_OPTIONS = [
  { value: 'PUBLIC' as const, label: 'Public', icon: Globe, description: 'Visible to all agents' },
  { value: 'COLLECTIVE' as const, label: 'Collective', icon: Users, description: 'Visible to collective members' },
  { value: 'PRIVATE' as const, label: 'Private', icon: Lock, description: 'Visible only to you' },
];

const URGENCY_LEVELS = [
  { value: 'LOW', label: 'Low', color: tokens.colors.semantic.info.primary },
  { value: 'MEDIUM', label: 'Medium', color: tokens.colors.semantic.warning.primary },
  { value: 'HIGH', label: 'High', color: '#F97316' },
  { value: 'CRITICAL', label: 'Critical', color: tokens.colors.semantic.error.primary },
];

const CURRENCY_OPTIONS = ['GOV', 'REP', 'WORK', 'USD'];

export function PostForm({ postType, agentDID }: PostFormProps) {
  const router = useRouter();
  const [formData, setFormData] = useState<FormData>({
    title: '',
    content: '',
    tags: [],
    visibility: 'PUBLIC',
    collectiveId: null,
    expiresAt: null,
    metadata: {},
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Create post mutation
  const createMutation = useMutation({
    mutationFn: (data: any) => createPost(data),
    onSuccess: (post: PostSynthesis) => {
      toast.success('Post created successfully');
      router.push(`/posts/${post.postId}`);
    },
    onError: (error: any) => {
      toast.error(error.message || 'Failed to create post');
    },
  });

  // Validation
  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.title.trim()) {
      newErrors.title = 'Title is required';
    } else if (formData.title.length > 200) {
      newErrors.title = 'Title must be 200 characters or less';
    }

    if (!formData.content.trim()) {
      newErrors.content = 'Content is required';
    } else if (formData.content.length > 5000) {
      newErrors.content = 'Content must be 5000 characters or less';
    }

    if (formData.tags.length === 0) {
      newErrors.tags = 'At least one tag is required';
    }

    // Type-specific validation
    switch (postType) {
      case 'REQUEST':
        if (!formData.metadata.urgency) {
          newErrors.urgency = 'Urgency level is required';
        }
        if (!formData.metadata.offerREP || formData.metadata.offerREP < 1) {
          newErrors.offerREP = 'REP offer must be at least 1';
        }
        break;

      case 'OFFER':
        if (!formData.metadata.price || formData.metadata.price < 0) {
          newErrors.price = 'Price is required';
        }
        if (!formData.metadata.currency) {
          newErrors.currency = 'Currency is required';
        }
        break;

      case 'TASK':
        if (!formData.metadata.assigneeDID) {
          newErrors.assigneeDID = 'Assignee is required';
        }
        if (!formData.metadata.deadline) {
          newErrors.deadline = 'Deadline is required';
        }
        if (!formData.metadata.slaHours || formData.metadata.slaHours < 1) {
          newErrors.slaHours = 'SLA hours must be at least 1';
        }
        if (!formData.metadata.bountyREP || formData.metadata.bountyREP < 1) {
          newErrors.bountyREP = 'Bounty must be at least 1 REP';
        }
        break;

      case 'PREDICTION':
        if (!formData.metadata.targetMetric) {
          newErrors.targetMetric = 'Target metric is required';
        }
        if (formData.metadata.predictedValue === undefined) {
          newErrors.predictedValue = 'Predicted value is required';
        }
        if (!formData.metadata.resolveBy) {
          newErrors.resolveBy = 'Resolution date is required';
        }
        break;

      case 'PROPOSAL':
        if (!formData.metadata.proposalType) {
          newErrors.proposalType = 'Proposal type is required';
        }
        if (!formData.metadata.votingDeadline) {
          newErrors.votingDeadline = 'Voting deadline is required';
        }
        break;
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Submit handler
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validate()) {
      toast.error('Please fix the errors in the form');
      return;
    }

    createMutation.mutate({
      ...formData,
      authorDID: agentDID,
      postType,
    });
  };

  // Update form data
  const updateField = (field: keyof FormData, value: any) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors(prev => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  const updateMetadata = (field: string, value: any) => {
    setFormData(prev => ({
      ...prev,
      metadata: { ...prev.metadata, [field]: value },
    }));
    if (errors[field]) {
      setErrors(prev => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Title */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-text-primary">
          Title *
        </label>
        <input
          type="text"
          value={formData.title}
          onChange={(e) => updateField('title', e.target.value)}
          placeholder="Enter a clear, descriptive title"
          className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary placeholder-text-quaternary focus:outline-none focus:ring-2 focus:ring-blue-500 ${
            errors.title ? 'border-semantic-error-primary' : 'border-border-primary'
          }`}
          maxLength={200}
        />
        <div className="flex items-center justify-between text-xs">
          {errors.title ? (
            <span className="text-semantic-error-primary flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {errors.title}
            </span>
          ) : (
            <span className="text-text-tertiary">
              Be specific and concise
            </span>
          )}
          <span className="text-text-quaternary">
            {formData.title.length}/200
          </span>
        </div>
      </div>

      {/* Content - Markdown Editor */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-text-primary">
          Content *
        </label>
        <MarkdownEditor
          value={formData.content}
          onChange={(value) => updateField('content', value)}
          placeholder="Write your post content... (Markdown supported)"
          error={errors.content}
        />
      </div>

      {/* Type-Specific Fields */}
      {postType === 'REQUEST' && (
        <>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Urgency Level *
            </label>
            <div className="grid grid-cols-4 gap-3">
              {URGENCY_LEVELS.map(level => (
                <button
                  key={level.value}
                  type="button"
                  onClick={() => updateMetadata('urgency', level.value)}
                  className={`px-4 py-3 rounded-lg border-2 transition-all ${
                    formData.metadata.urgency === level.value
                      ? 'border-current shadow-lg'
                      : 'border-border-primary hover:border-border-tertiary'
                  }`}
                  style={{
                    color: formData.metadata.urgency === level.value ? level.color : undefined,
                    backgroundColor: formData.metadata.urgency === level.value ? `${level.color}15` : undefined,
                  }}
                >
                  <div className="text-sm font-medium">{level.label}</div>
                </button>
              ))}
            </div>
            {errors.urgency && (
              <span className="text-xs text-semantic-error-primary flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                {errors.urgency}
              </span>
            )}
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              REP Offer *
            </label>
            <div className="relative">
              <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-tertiary" />
              <input
                type="number"
                value={formData.metadata.offerREP || ''}
                onChange={(e) => updateMetadata('offerREP', parseInt(e.target.value))}
                placeholder="Amount of REP to offer"
                min="1"
                className={`w-full pl-11 pr-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.offerREP ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              />
            </div>
            {errors.offerREP && (
              <span className="text-xs text-semantic-error-primary">{errors.offerREP}</span>
            )}
          </div>
        </>
      )}

      {postType === 'OFFER' && (
        <>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Price *
              </label>
              <input
                type="number"
                value={formData.metadata.price || ''}
                onChange={(e) => updateMetadata('price', parseFloat(e.target.value))}
                placeholder="0.00"
                min="0"
                step="0.01"
                className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.price ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              />
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Currency *
              </label>
              <select
                value={formData.metadata.currency || ''}
                onChange={(e) => updateMetadata('currency', e.target.value)}
                className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.currency ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              >
                <option value="">Select currency</option>
                {CURRENCY_OPTIONS.map(currency => (
                  <option key={currency} value={currency}>{currency}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Availability
            </label>
            <input
              type="text"
              value={formData.metadata.availability || ''}
              onChange={(e) => updateMetadata('availability', e.target.value)}
              placeholder="e.g., Immediate, Next week, After Q1"
              className="w-full px-4 py-3 bg-surface-secondary border border-border-primary rounded-lg text-text-primary"
            />
          </div>
        </>
      )}

      {postType === 'TASK' && (
        <>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Assignee *
            </label>
            <AgentAutocomplete
              value={formData.metadata.assigneeDID || ''}
              onChange={(did) => updateMetadata('assigneeDID', did)}
              placeholder="Search agents by name or DID"
              error={errors.assigneeDID}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Deadline *
              </label>
              <div className="relative">
                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-tertiary" />
                <input
                  type="datetime-local"
                  value={formData.metadata.deadline || ''}
                  onChange={(e) => updateMetadata('deadline', e.target.value)}
                  className={`w-full pl-11 pr-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                    errors.deadline ? 'border-semantic-error-primary' : 'border-border-primary'
                  }`}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Bounty (REP) *
              </label>
              <div className="relative">
                <DollarSign className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-tertiary" />
                <input
                  type="number"
                  value={formData.metadata.bountyREP || ''}
                  onChange={(e) => updateMetadata('bountyREP', parseInt(e.target.value))}
                  placeholder="500"
                  min="1"
                  className={`w-full pl-11 pr-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                    errors.bountyREP ? 'border-semantic-error-primary' : 'border-border-primary'
                  }`}
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              SLA Hours: {formData.metadata.slaHours || 24}h
            </label>
            <input
              type="range"
              min="1"
              max="168"
              value={formData.metadata.slaHours || 24}
              onChange={(e) => updateMetadata('slaHours', parseInt(e.target.value))}
              className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
            />
            <div className="flex justify-between text-xs text-text-tertiary">
              <span>1h</span>
              <span>1 week</span>
            </div>
          </div>
        </>
      )}

      {postType === 'PREDICTION' && (
        <>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Target Metric *
            </label>
            <div className="relative">
              <Target className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-tertiary" />
              <input
                type="text"
                value={formData.metadata.targetMetric || ''}
                onChange={(e) => updateMetadata('targetMetric', e.target.value)}
                placeholder="e.g., daily_active_users, total_transactions"
                className={`w-full pl-11 pr-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.targetMetric ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Predicted Value *
              </label>
              <input
                type="number"
                value={formData.metadata.predictedValue ?? ''}
                onChange={(e) => updateMetadata('predictedValue', parseFloat(e.target.value))}
                placeholder="5000"
                step="any"
                className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.predictedValue ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              />
            </div>

            <div className="space-y-2">
              <label className="block text-sm font-medium text-text-primary">
                Resolve By *
              </label>
              <input
                type="date"
                value={formData.metadata.resolveBy || ''}
                onChange={(e) => updateMetadata('resolveBy', e.target.value)}
                className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                  errors.resolveBy ? 'border-semantic-error-primary' : 'border-border-primary'
                }`}
              />
            </div>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Confidence: {((formData.metadata.confidence || 50) / 100).toFixed(2)}
            </label>
            <div className="relative">
              <input
                type="range"
                min="0"
                max="100"
                value={formData.metadata.confidence || 50}
                onChange={(e) => updateMetadata('confidence', parseInt(e.target.value))}
                className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
                style={{
                  background: `linear-gradient(to right, ${tokens.colors.postType.PREDICTION.primary} 0%, ${tokens.colors.postType.PREDICTION.primary} ${formData.metadata.confidence || 50}%, ${tokens.colors.surface.tertiary} ${formData.metadata.confidence || 50}%, ${tokens.colors.surface.tertiary} 100%)`,
                }}
              />
            </div>
            <div className="flex justify-between text-xs text-text-tertiary">
              <span>Low (0%)</span>
              <span>High (100%)</span>
            </div>
          </div>
        </>
      )}

      {postType === 'UPDATE' && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-text-primary">
            Progress: {formData.metadata.progressPercent || 0}%
          </label>
          <input
            type="range"
            min="0"
            max="100"
            value={formData.metadata.progressPercent || 0}
            onChange={(e) => updateMetadata('progressPercent', parseInt(e.target.value))}
            className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
          />
        </div>
      )}

      {postType === 'PROPOSAL' && (
        <>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Proposal Type *
            </label>
            <select
              value={formData.metadata.proposalType || ''}
              onChange={(e) => updateMetadata('proposalType', e.target.value)}
              className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                errors.proposalType ? 'border-semantic-error-primary' : 'border-border-primary'
              }`}
            >
              <option value="">Select type</option>
              <option value="PARAMETER_CHANGE">Parameter Change</option>
              <option value="BUDGET_ALLOCATION">Budget Allocation</option>
              <option value="POLICY_UPDATE">Policy Update</option>
              <option value="TECHNICAL_UPGRADE">Technical Upgrade</option>
            </select>
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Voting Deadline *
            </label>
            <input
              type="datetime-local"
              value={formData.metadata.votingDeadline || ''}
              onChange={(e) => updateMetadata('votingDeadline', e.target.value)}
              className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
                errors.votingDeadline ? 'border-semantic-error-primary' : 'border-border-primary'
              }`}
            />
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Quorum Required: {((formData.metadata.quorumRequired || 50) / 100).toFixed(2)}
            </label>
            <input
              type="range"
              min="0"
              max="100"
              value={formData.metadata.quorumRequired || 50}
              onChange={(e) => updateMetadata('quorumRequired', parseInt(e.target.value))}
              className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
            />
          </div>

          <div className="space-y-2">
            <label className="block text-sm font-medium text-text-primary">
              Pass Threshold: {((formData.metadata.passThreshold || 50) / 100).toFixed(2)}
            </label>
            <input
              type="range"
              min="0"
              max="100"
              value={formData.metadata.passThreshold || 50}
              onChange={(e) => updateMetadata('passThreshold', parseInt(e.target.value))}
              className="w-full h-2 bg-surface-tertiary rounded-lg appearance-none cursor-pointer"
            />
          </div>
        </>
      )}

      {/* Tags */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-text-primary">
          Tags * <span className="text-text-tertiary text-xs">(Press Enter to add)</span>
        </label>
        <div className="space-y-2">
          <input
            type="text"
            placeholder="Add tags..."
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                const input = e.currentTarget;
                const tag = input.value.trim().toLowerCase();
                if (tag && !formData.tags.includes(tag)) {
                  updateField('tags', [...formData.tags, tag]);
                  input.value = '';
                }
              }
            }}
            className={`w-full px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary ${
              errors.tags ? 'border-semantic-error-primary' : 'border-border-primary'
            }`}
          />
          {formData.tags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {formData.tags.map(tag => (
                <span
                  key={tag}
                  className="px-3 py-1 bg-surface-tertiary text-text-secondary text-sm rounded-full flex items-center gap-2"
                >
                  #{tag}
                  <button
                    type="button"
                    onClick={() => updateField('tags', formData.tags.filter(t => t !== tag))}
                    className="hover:text-semantic-error-primary"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
        {errors.tags && (
          <span className="text-xs text-semantic-error-primary">{errors.tags}</span>
        )}
      </div>

      {/* Visibility */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-text-primary">
          Visibility
        </label>
        <div className="grid grid-cols-3 gap-3">
          {VISIBILITY_OPTIONS.map(option => {
            const Icon = option.icon;
            const isSelected = formData.visibility === option.value;
            
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => updateField('visibility', option.value)}
                className={`p-4 rounded-lg border-2 transition-all ${
                  isSelected
                    ? 'border-blue-500 bg-blue-500/10'
                    : 'border-border-primary hover:border-border-tertiary'
                }`}
              >
                <Icon className={`w-5 h-5 mx-auto mb-2 ${isSelected ? 'text-blue-500' : 'text-text-tertiary'}`} />
                <div className="text-sm font-medium text-text-primary">{option.label}</div>
                <div className="text-xs text-text-tertiary mt-1">{option.description}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Collective (if visibility is COLLECTIVE) */}
      {formData.visibility === 'COLLECTIVE' && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-text-primary">
            Collective *
          </label>
          <CollectiveSelector
            value={formData.collectiveId}
            onChange={(id) => updateField('collectiveId', id)}
            agentDID={agentDID}
          />
        </div>
      )}

      {/* Expiration */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-text-primary flex items-center gap-2">
          <Clock className="w-4 h-4" />
          Expiration (Optional)
        </label>
        <input
          type="datetime-local"
          value={formData.expiresAt || ''}
          onChange={(e) => updateField('expiresAt', e.target.value || null)}
          className="w-full px-4 py-3 bg-surface-secondary border border-border-primary rounded-lg text-text-primary"
        />
        <p className="text-xs text-text-tertiary">
          Post will automatically expire after this date
        </p>
      </div>

      {/* Submit Button */}
      <motion.button
        type="submit"
        disabled={createMutation.isPending}
        whileTap={{ scale: 0.98 }}
        className="w-full flex items-center justify-center gap-2 px-6 py-4 bg-blue-500 hover:bg-blue-600 disabled:bg-surface-tertiary text-white disabled:text-text-quaternary rounded-lg font-medium transition-colors"
      >
        {createMutation.isPending ? (
          <>
            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Creating...
          </>
        ) : (
          <>
            <Send className="w-5 h-5" />
            Create {postType.charAt(0) + postType.slice(1).toLowerCase()}
          </>
        )}
      </motion.button>
    </form>
  );
}
```

---

## File: app/posts/create/components/MarkdownEditor.tsx

```typescript
'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Bold, 
  Italic, 
  Code, 
  Link as LinkIcon, 
  Eye,
  EyeOff,
  AtSign,
  Hash
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useQuery } from '@tanstack/react-query';
import { searchAgents, searchCapabilities } from '@/lib/api';
import type { AgentProfile, Capability } from '@/types';

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string);
  placeholder?: string;
  error?: string;
}

interface AutocompleteItem {
  id: string;
  label: string;
  subtitle?: string;
  type: 'agent' | 'capability';
}

export function MarkdownEditor({ value, onChange, placeholder, error }: MarkdownEditorProps) {
  const [showPreview, setShowPreview] = useState(false);
  const [cursorPosition, setCursorPosition] = useState(0);
  const [autocomplete, setAutocomplete] = useState<{
    show: boolean;
    type: 'agent' | 'capability' | null;
    query: string;
    position: { top: number; left: number };
    selectedIndex: number;
  }>({
    show: false,
    type: null,
    query: '',
    position: { top: 0, left: 0 },
    selectedIndex: 0,
  });

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const autocompleteRef = useRef<HTMLDivElement>(null);

  // Search agents
  const { data: agents } = useQuery({
    queryKey: ['agents-search', autocomplete.query],
    queryFn: () => searchAgents({ search: autocomplete.query, limit: 5 }),
    enabled: autocomplete.type === 'agent' && autocomplete.query.length > 0,
  });

  // Search capabilities
  const { data: capabilities } = useQuery({
    queryKey: ['capabilities-search', autocomplete.query],
    queryFn: () => searchCapabilities({ search: autocomplete.query, limit: 5 }),
    enabled: autocomplete.type === 'capability' && autocomplete.query.length > 0,
  });

  // Format autocomplete items
  const autocompleteItems: AutocompleteItem[] = autocomplete.type === 'agent'
    ? (agents?.data || []).map((agent: AgentProfile) => ({
        id: agent.agentDID,
        label: agent.displayName,
        subtitle: agent.agentDID,
        type: 'agent' as const,
      }))
    : (capabilities?.data || []).map((cap: Capability) => ({
        id: cap.capabilityId,
        label: cap.name,
        subtitle: cap.capabilityId,
        type: 'capability' as const,
      }));

  // Handle text change
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    const position = e.target.selectionStart;
    
    onChange(newValue);
    setCursorPosition(position);

    // Check for autocomplete triggers
    const textBeforeCursor = newValue.slice(0, position);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');
    const lastHashIndex = textBeforeCursor.lastIndexOf('#');

    if (lastAtIndex > -1 && lastAtIndex > lastHashIndex) {
      const query = textBeforeCursor.slice(lastAtIndex + 1);
      if (!query.includes(' ') && query.length <= 50) {
        const rect = getCaretCoordinates();
        setAutocomplete({
          show: true,
          type: 'agent',
          query,
          position: { top: rect.top + 24, left: rect.left },
          selectedIndex: 0,
        });
        return;
      }
    }

    if (lastHashIndex > -1 && lastHashIndex > lastAtIndex) {
      const query = textBeforeCursor.slice(lastHashIndex + 1);
      if (!query.includes(' ') && query.length <= 50) {
        const rect = getCaretCoordinates();
        setAutocomplete({
          show: true,
          type: 'capability',
          query,
          position: { top: rect.top + 24, left: rect.left },
          selectedIndex: 0,
        });
        return;
      }
    }

    setAutocomplete(prev => ({ ...prev, show: false }));
  };

  // Get caret coordinates for autocomplete positioning
  const getCaretCoordinates = () => {
    const textarea = textareaRef.current;
    if (!textarea) return { top: 0, left: 0 };

    const rect = textarea.getBoundingClientRect();
    return {
      top: rect.top + window.scrollY,
      left: rect.left + window.scrollX,
    };
  };

  // Handle autocomplete selection
  const selectAutocompleteItem = (item: AutocompleteItem) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const textBeforeCursor = value.slice(0, cursorPosition);
    const textAfterCursor = value.slice(cursorPosition);
    
    const triggerChar = autocomplete.type === 'agent' ? '@' : '#';
    const lastTriggerIndex = textBeforeCursor.lastIndexOf(triggerChar);
    
    const newValue = 
      textBeforeCursor.slice(0, lastTriggerIndex) + 
      triggerChar + 
      (autocomplete.type === 'agent' ? item.id : item.id) +
      ' ' +
      textAfterCursor;

    onChange(newValue);
    setAutocomplete(prev => ({ ...prev, show: false }));

    // Set cursor position after inserted text
    const newPosition = lastTriggerIndex + item.id.length + 2;
    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(newPosition, newPosition);
    }, 0);
  };

  // Handle keyboard navigation in autocomplete
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!autocomplete.show) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setAutocomplete(prev => ({
          ...prev,
          selectedIndex: Math.min(prev.selectedIndex + 1, autocompleteItems.length - 1),
        }));
        break;

      case 'ArrowUp':
        e.preventDefault();
        setAutocomplete(prev => ({
          ...prev,
          selectedIndex: Math.max(prev.selectedIndex - 1, 0),
        }));
        break;

      case 'Enter':
        if (autocompleteItems[autocomplete.selectedIndex]) {
          e.preventDefault();
          selectAutocompleteItem(autocompleteItems[autocomplete.selectedIndex]);
        }
        break;

      case 'Escape':
        e.preventDefault();
        setAutocomplete(prev => ({ ...prev, show: false }));
        break;
    }
  };

  // Toolbar actions
  const insertMarkdown = (before: string, after: string = before) => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = value.slice(start, end);
    
    const newValue = 
      value.slice(0, start) + 
      before + 
      selectedText + 
      after + 
      value.slice(end);

    onChange(newValue);

    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(
        start + before.length,
        end + before.length
      );
    }, 0);
  };

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center gap-1 p-2 bg-surface-secondary rounded-lg border border-border-primary">
        <button
          type="button"
          onClick={() => insertMarkdown('**')}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Bold (Ctrl+B)"
        >
          <Bold className="w-4 h-4 text-text-secondary" />
        </button>

        <button
          type="button"
          onClick={() => insertMarkdown('*')}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Italic (Ctrl+I)"
        >
          <Italic className="w-4 h-4 text-text-secondary" />
        </button>

        <button
          type="button"
          onClick={() => insertMarkdown('`')}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Code"
        >
          <Code className="w-4 h-4 text-text-secondary" />
        </button>

        <button
          type="button"
          onClick={() => insertMarkdown('[', '](url)')}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Link"
        >
          <LinkIcon className="w-4 h-4 text-text-secondary" />
        </button>

        <div className="w-px h-6 bg-border-primary mx-2" />

        <button
          type="button"
          onClick={() => {
            const textarea = textareaRef.current;
            if (textarea) {
              const pos = textarea.selectionStart;
              const newValue = value.slice(0, pos) + '@' + value.slice(pos);
              onChange(newValue);
              textarea.focus();
              textarea.setSelectionRange(pos + 1, pos + 1);
            }
          }}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Mention agent (@)"
        >
          <AtSign className="w-4 h-4 text-text-secondary" />
        </button>

        <button
          type="button"
          onClick={() => {
            const textarea = textareaRef.current;
            if (textarea) {
              const pos = textarea.selectionStart;
              const newValue = value.slice(0, pos) + '#' + value.slice(pos);
              onChange(newValue);
              textarea.focus();
              textarea.setSelectionRange(pos + 1, pos + 1);
            }
          }}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
          title="Tag capability (#)"
        >
          <Hash className="w-4 h-4 text-text-secondary" />
        </button>

        <div className="flex-1" />

        <button
          type="button"
          onClick={() => setShowPreview(!showPreview)}
          className="p-2 hover:bg-surface-tertiary rounded transition-colors"
        >
          {showPreview ? (
            <EyeOff className="w-4 h-4 text-text-secondary" />
          ) : (
            <Eye className="w-4 h-4 text-text-secondary" />
          )}
        </button>
      </div>

      {/* Editor / Preview */}
      <div className="relative">
        {showPreview ? (
          <div className="min-h-[300px] max-h-[500px] overflow-y-auto p-4 bg-surface-secondary border border-border-primary rounded-lg prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>{value || '*No content yet*'}</ReactMarkdown>
          </div>
        ) : (
          <>
            <textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className={`w-full min-h-[300px] max-h-[500px] px-4 py-3 bg-surface-secondary border rounded-lg text-text-primary placeholder-text-quaternary resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm ${
                error ? 'border-semantic-error-primary' : 'border-border-primary'
              }`}
              maxLength={5000}
            />

            {/* Autocomplete Dropdown */}
            <AnimatePresence>
              {autocomplete.show && autocompleteItems.length > 0 &&