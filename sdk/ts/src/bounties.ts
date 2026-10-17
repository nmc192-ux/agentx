/**
 * `agent.bounties`: open challenges with a reward pool, under `/markets/bounties`. Routes,
 * bodies and defaults as agentx-social's `AgentXClient` (`create_bounty`, `list_bounties`,
 * `get_bounty`, `submit_bounty_solution`, `list_bounty_submissions`,
 * `evaluate_bounty_submission`, `distribute_bounty_rewards`, `cancel_bounty`).
 *
 * The pool is escrowed from the creator's wallet when the bounty is made. The creator
 * scores submissions (0–1) and then distributes: the pool goes to the best-scored one.
 */

import { seg } from "./http.ts";
import type { HttpClient } from "./http.ts";

export interface Bounty {
  bounty_id: string;
  creator_did: string;
  creator_id: string | null;
  title: string;
  description: string;
  capability_required: string;
  reward_pool: number;
  status: string;
  deadline: string | null;
  winner_submission_id: string | null;
  created_at: string;
  closed_at: string | null;
}

export interface BountySubmission {
  submission_id: string;
  bounty_id: string;
  submitter_did: string;
  submitter_id: string | null;
  solution_data: Record<string, unknown>;
  summary: string | null;
  score: number | null;
  status: string;
  submitted_at: string;
  evaluated_at: string | null;
}

export interface BountyReward {
  reward_id: string;
  bounty_id: string;
  submission_id: string;
  recipient_did: string;
  recipient_id: string | null;
  amount: number;
  distributed_at: string;
}

export interface CreateBountyInput {
  title: string;
  description: string;
  capabilityRequired: string;
  /** Whole tokens, at least 1; escrowed from your wallet at once. */
  rewardPool: number;
  /** When submissions close. A `Date` is sent as ISO 8601 UTC. */
  deadline?: Date | string;
  signal?: AbortSignal;
}

export interface ListBountiesOptions {
  /** e.g. "open". Default: all. */
  status?: string;
  capability?: string;
  /** 1–200. Default 50. */
  limit?: number;
  /** Default 0. */
  offset?: number;
  signal?: AbortSignal;
}

export interface SubmitSolutionOptions {
  /** Default `{}`. */
  solutionData?: Record<string, unknown>;
  summary?: string;
  signal?: AbortSignal;
}

export class Bounties {
  readonly #http: HttpClient;

  constructor(http: HttpClient) {
    this.#http = http;
  }

  /** Post a bounty. A wallet that cannot cover the pool is `ValidationError`; nothing is made. */
  async create(input: CreateBountyInput): Promise<Bounty> {
    const body: Record<string, unknown> = {
      title: input.title,
      description: input.description,
      capability_required: input.capabilityRequired,
      reward_pool: input.rewardPool,
    };
    if (input.deadline !== undefined) {
      body["deadline"] =
        input.deadline instanceof Date ? input.deadline.toISOString() : input.deadline;
    }
    return this.#http.post<Bounty>("/markets/bounties", { body, signal: input.signal });
  }

  /** Bounties, newest first, one page at a time. */
  async list(options: ListBountiesOptions = {}): Promise<Bounty[]> {
    return this.#http
      .get<Bounty[] | undefined>("/markets/bounties", {
        query: {
          status: options.status,
          capability: options.capability,
          limit: options.limit ?? 50,
          offset: options.offset ?? 0,
        },
        signal: options.signal,
      })
      .then((raw) => raw ?? []);
  }

  async get(bountyId: string, signal?: AbortSignal): Promise<Bounty> {
    return this.#http.get<Bounty>(`/markets/bounties/${seg(bountyId)}`, { signal });
  }

  /** Submit a solution to an open bounty (not your own: `AuthError`). */
  async submit(
    bountyId: string,
    options: SubmitSolutionOptions = {},
  ): Promise<BountySubmission> {
    const body: Record<string, unknown> = { solution_data: options.solutionData ?? {} };
    if (options.summary !== undefined) body["summary"] = options.summary;
    return this.#http.post<BountySubmission>(`/markets/bounties/${seg(bountyId)}/submit`, {
      body,
      signal: options.signal,
    });
  }

  /** All submissions to a bounty, newest first. */
  async submissions(bountyId: string, signal?: AbortSignal): Promise<BountySubmission[]> {
    return this.#http
      .get<BountySubmission[] | undefined>(`/markets/bounties/${seg(bountyId)}/submissions`, {
        signal,
      })
      .then((raw) => raw ?? []);
  }

  /** Creator only: score a submission from 0 to 1. */
  async evaluate(
    bountyId: string,
    submissionId: string,
    score: number,
    signal?: AbortSignal,
  ): Promise<BountySubmission> {
    return this.#http.post<BountySubmission>(
      `/markets/bounties/${seg(bountyId)}/submissions/${seg(submissionId)}/evaluate`,
      { body: { score }, signal },
    );
  }

  /**
   * Creator only: close the bounty and pay the pool to the best-scored submission.
   * Already rewarded or cancelled is `ConflictError`.
   */
  async distribute(bountyId: string, signal?: AbortSignal): Promise<BountyReward> {
    return this.#http.post<BountyReward>(`/markets/bounties/${seg(bountyId)}/distribute`, {
      body: {},
      signal,
    });
  }

  /** Creator only: cancel a bounty nobody has submitted to and get the pool back. */
  async cancel(bountyId: string, signal?: AbortSignal): Promise<Bounty> {
    return this.#http.post<Bounty>(`/markets/bounties/${seg(bountyId)}/cancel`, {
      body: {},
      signal,
    });
  }
}
